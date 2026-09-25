"""
VM State Comparator - Interactive GUI tool for capturing and comparing VM screenshots.

Usage:
    python tools/state_comparator.py
    python tools/state_comparator.py --path_to_vm "path/to/your.vmx"
    python tools/state_comparator.py --vm_ip 192.168.x.x --vm_port 5000   # skip VM boot, connect directly
"""

import sys
import os
import io
import argparse
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# VM connection helpers
# ---------------------------------------------------------------------------

def boot_vm_and_get_controller(path_to_vm: str, provider_name: str = "vmware"):
    """Boot the VM via OSWorld provider and return a PythonController."""
    from gui_rewalk.env.osworld_reload import PythonController
    from OSWorld.desktop_env.providers import create_vm_manager_and_provider

    manager, provider = create_vm_manager_and_provider(provider_name, None, use_proxy=False)
    path_to_vm = os.path.abspath(os.path.expandvars(os.path.expanduser(path_to_vm)))
    provider.start_emulator(path_to_vm, False, "Ubuntu")

    vm_ip_ports = provider.get_ip_address(path_to_vm).split(":")
    vm_ip = vm_ip_ports[0]
    server_port = int(vm_ip_ports[1]) if len(vm_ip_ports) > 1 else 5000
    controller = PythonController(vm_ip=vm_ip, server_port=server_port)
    return controller, provider, path_to_vm


def connect_to_vm(vm_ip: str, vm_port: int):
    """Connect directly to a running VM (no boot)."""
    from gui_rewalk.env.osworld_reload import PythonController
    return PythonController(vm_ip=vm_ip, server_port=vm_port)


# ---------------------------------------------------------------------------
# SSIM comparison (reuse project algorithm)
# ---------------------------------------------------------------------------

def compare_screenshots(path1: str, path2: str) -> float:
    from gui_rewalk.src.core.reverse.image_ssim_calculator import get_image_ssim
    return get_image_ssim(path1, path2)


def interpret_ssim(score: float) -> tuple:
    """Return (label, color) based on SSIM thresholds from graph_enricher."""
    if score > 0.95:
        return "IDENTICAL (static page)", "#2ecc71"
    elif score > 0.50:
        return "SIMILAR (dynamic content)", "#f39c12"
    else:
        return "DIFFERENT (new state)", "#e74c3c"


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------

class StateComparatorApp:
    THUMB_W = 640
    THUMB_H = 360

    def __init__(self, root: tk.Tk, controller, provider=None, path_to_vm=None):
        self.root = root
        self.controller = controller
        self.provider = provider
        self.path_to_vm = path_to_vm

        self.root.title("VM State Comparator")
        self.root.configure(bg="#2c3e50")
        self.root.resizable(True, True)

        # State storage
        self.screenshots = [None, None]  # raw bytes
        self.tmp_paths = [None, None]    # saved file paths
        self.photo_refs = [None, None]   # keep PhotoImage references alive

        self._build_ui()

    # ---- UI construction ----

    def _build_ui(self):
        # Top bar
        top = tk.Frame(self.root, bg="#34495e", pady=8)
        top.pack(fill=tk.X)
        tk.Label(top, text="VM State Comparator", font=("Segoe UI", 16, "bold"),
                 fg="white", bg="#34495e").pack()

        # Main area: two panels side by side
        main = tk.Frame(self.root, bg="#2c3e50")
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        self.panels = []
        for idx, label in enumerate(["State A (Before)", "State B (After)"]):
            panel = self._build_panel(main, idx, label)
            panel.grid(row=0, column=idx, sticky="nsew", padx=5, pady=5)
            self.panels.append(panel)
        main.rowconfigure(0, weight=1)

        # Bottom bar: compare button + result
        bottom = tk.Frame(self.root, bg="#2c3e50", pady=10)
        bottom.pack(fill=tk.X)

        btn_frame = tk.Frame(bottom, bg="#2c3e50")
        btn_frame.pack()

        self.compare_btn = tk.Button(
            btn_frame, text="Compare States (SSIM)",
            font=("Segoe UI", 13, "bold"), bg="#2980b9", fg="white",
            activebackground="#3498db", padx=20, pady=8,
            command=self._on_compare, state=tk.DISABLED,
        )
        self.compare_btn.pack(side=tk.LEFT, padx=10)

        self.load_a_btn = tk.Button(
            btn_frame, text="Load Image A",
            font=("Segoe UI", 10), bg="#7f8c8d", fg="white",
            command=lambda: self._on_load_file(0),
        )
        self.load_a_btn.pack(side=tk.LEFT, padx=5)

        self.load_b_btn = tk.Button(
            btn_frame, text="Load Image B",
            font=("Segoe UI", 10), bg="#7f8c8d", fg="white",
            command=lambda: self._on_load_file(1),
        )
        self.load_b_btn.pack(side=tk.LEFT, padx=5)

        # Result label
        self.result_var = tk.StringVar(value="Capture two states, then click Compare.")
        self.result_label = tk.Label(
            bottom, textvariable=self.result_var,
            font=("Segoe UI", 14), fg="#ecf0f1", bg="#2c3e50",
        )
        self.result_label.pack(pady=(10, 0))

        # SSIM progress bar
        self.ssim_bar = ttk.Progressbar(bottom, length=400, maximum=100)
        self.ssim_bar.pack(pady=(5, 0))

    def _build_panel(self, parent, idx, title):
        frame = tk.LabelFrame(
            parent, text=title, font=("Segoe UI", 12, "bold"),
            fg="white", bg="#34495e", labelanchor="n",
        )

        # Image canvas
        canvas = tk.Canvas(frame, width=self.THUMB_W, height=self.THUMB_H,
                           bg="#1a252f", highlightthickness=0)
        canvas.pack(padx=10, pady=(10, 5), fill=tk.BOTH, expand=True)
        setattr(self, f"canvas_{idx}", canvas)

        # Info label
        info = tk.Label(frame, text="No capture yet", font=("Segoe UI", 9),
                        fg="#bdc3c7", bg="#34495e")
        info.pack()
        setattr(self, f"info_{idx}", info)

        # Capture button
        btn = tk.Button(
            frame, text=f"Capture State {'A' if idx == 0 else 'B'}",
            font=("Segoe UI", 11, "bold"),
            bg="#27ae60" if idx == 0 else "#e67e22",
            fg="white", activebackground="#2ecc71" if idx == 0 else "#f39c12",
            padx=15, pady=6,
            command=lambda i=idx: self._on_capture(i),
        )
        btn.pack(pady=(5, 10))

        return frame

    # ---- Actions ----

    def _on_capture(self, idx):
        """Capture a screenshot from the VM and display it."""
        info_label: tk.Label = getattr(self, f"info_{idx}")
        info_label.config(text="Capturing...")
        self.root.update_idletasks()

        def do_capture():
            try:
                raw = self.controller.get_screenshot()
                if raw is None:
                    self.root.after(0, lambda: messagebox.showerror("Error", "Failed to get screenshot from VM."))
                    self.root.after(0, lambda: info_label.config(text="Capture failed"))
                    return
                self.screenshots[idx] = raw

                # Save to temp file for SSIM calculation
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False,
                                                   prefix=f"state_{'a' if idx == 0 else 'b'}_")
                tmp.write(raw)
                tmp.close()
                if self.tmp_paths[idx] and os.path.exists(self.tmp_paths[idx]):
                    os.unlink(self.tmp_paths[idx])
                self.tmp_paths[idx] = tmp.name

                # Display
                self.root.after(0, lambda: self._display_image(idx, raw))
                ts = datetime.now().strftime("%H:%M:%S")
                self.root.after(0, lambda: info_label.config(text=f"Captured at {ts}"))
                self.root.after(0, self._update_compare_btn)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
                self.root.after(0, lambda: info_label.config(text="Capture failed"))

        threading.Thread(target=do_capture, daemon=True).start()

    def _on_load_file(self, idx):
        """Load a screenshot from a local file instead of capturing from VM."""
        path = filedialog.askopenfilename(
            title=f"Select image for State {'A' if idx == 0 else 'B'}",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")],
        )
        if not path:
            return
        with open(path, "rb") as f:
            raw = f.read()
        self.screenshots[idx] = raw

        if self.tmp_paths[idx] and os.path.exists(self.tmp_paths[idx]):
            os.unlink(self.tmp_paths[idx])
        self.tmp_paths[idx] = path  # use original path directly

        self._display_image(idx, raw)
        info_label: tk.Label = getattr(self, f"info_{idx}")
        info_label.config(text=f"Loaded: {os.path.basename(path)}")
        self._update_compare_btn()

    def _display_image(self, idx, raw_bytes):
        canvas: tk.Canvas = getattr(self, f"canvas_{idx}")
        img = Image.open(io.BytesIO(raw_bytes))

        # Fit to canvas
        cw = canvas.winfo_width() or self.THUMB_W
        ch = canvas.winfo_height() or self.THUMB_H
        img.thumbnail((cw, ch), Image.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        self.photo_refs[idx] = photo  # prevent GC
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, image=photo, anchor=tk.CENTER)

    def _update_compare_btn(self):
        if self.tmp_paths[0] and self.tmp_paths[1]:
            self.compare_btn.config(state=tk.NORMAL)
        else:
            self.compare_btn.config(state=tk.DISABLED)

    def _on_compare(self):
        if not self.tmp_paths[0] or not self.tmp_paths[1]:
            messagebox.showwarning("Warning", "Please capture both states first.")
            return

        self.result_var.set("Calculating SSIM...")
        self.root.update_idletasks()

        def do_compare():
            try:
                score = compare_screenshots(self.tmp_paths[0], self.tmp_paths[1])
                label, color = interpret_ssim(score)
                self.root.after(0, lambda: self._show_result(score, label, color))
            except Exception as e:
                self.root.after(0, lambda: self.result_var.set(f"Error: {e}"))

        threading.Thread(target=do_compare, daemon=True).start()

    def _show_result(self, score, label, color):
        self.result_var.set(f"SSIM = {score:.4f}  |  {label}")
        self.result_label.config(fg=color)
        self.ssim_bar["value"] = max(0, score * 100)

    def on_close(self):
        # Clean up temp files
        for p in self.tmp_paths:
            if p and os.path.exists(p) and p.startswith(tempfile.gettempdir()):
                try:
                    os.unlink(p)
                except OSError:
                    pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="VM State Comparator GUI")
    parser.add_argument(
        "--path_to_vm", type=str,
        default=r"C:\Users\Admin\Desktop\GUI agent\GUI-ReWalk\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx",
        help="Path to .vmx file",
    )
    parser.add_argument("--vm_provider", type=str, default="vmware")
    parser.add_argument("--vm_ip", type=str, default=None,
                        help="Connect directly to a running VM (skip boot)")
    parser.add_argument("--vm_port", type=int, default=5000)
    parser.add_argument("--no_vm", action="store_true",
                        help="Offline mode: only load local images for comparison")
    return parser.parse_args()


def main():
    args = parse_args()

    controller = None
    provider = None
    path_to_vm = None

    if args.no_vm:
        print("[INFO] Offline mode - no VM connection. Use 'Load Image' buttons.")
    elif args.vm_ip:
        print(f"[INFO] Connecting to running VM at {args.vm_ip}:{args.vm_port}...")
        controller = connect_to_vm(args.vm_ip, args.vm_port)
        print("[INFO] Connected.")
    else:
        print(f"[INFO] Booting VM from {args.path_to_vm} ...")
        controller, provider, path_to_vm = boot_vm_and_get_controller(
            args.path_to_vm, args.vm_provider
        )
        print("[INFO] VM is running.")

    root = tk.Tk()
    root.geometry("1400x750")
    app = StateComparatorApp(root, controller, provider, path_to_vm)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
