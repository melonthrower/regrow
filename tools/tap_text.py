#!/usr/bin/env python3
"""adb uiautomator 文字定位点击: 在当前界面找含 <target> 文本/描述的节点, 点其中心。
用法: tap_text.py <console_port> <target_substring> [--type "要输入的文字"]
找不到 -> 退出码 1 并打印 NOT_FOUND(+列出当前可见文本)。"""
import sys, re, subprocess

port, target = sys.argv[1], sys.argv[2]
type_text = None
if "--type" in sys.argv:
    type_text = sys.argv[sys.argv.index("--type") + 1]
adb = ["/home/shenghonghui/android-sdk/platform-tools/adb", "-s", f"emulator-{port}"]

subprocess.run(adb + ["shell", "uiautomator", "dump"], capture_output=True)
xml = subprocess.run(adb + ["shell", "cat", "/sdcard/window_dump.xml"],
                     capture_output=True, text=True).stdout

def find(t):
    pats = [
        r'(?:text|content-desc)="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?(?:text|content-desc)="([^"]*)"',
    ]
    for i, p in enumerate(pats):
        for m in re.finditer(p, xml):
            g = m.groups()
            txt = g[0] if i == 0 else g[4]
            nums = g[1:5] if i == 0 else g[0:4]
            if t.lower() in (txt or "").lower():
                x1, y1, x2, y2 = map(int, nums)
                return (x1 + x2) // 2, (y1 + y2) // 2, txt
    return None

hit = find(target)
if not hit:
    seen = sorted(set(re.findall(r'text="([^"]+)"', xml)))
    print("NOT_FOUND:", target, "| 可见文本:", seen[:25])
    sys.exit(1)
x, y, txt = hit
subprocess.run(adb + ["shell", "input", "tap", str(x), str(y)])
print(f"TAPPED '{txt}' @ {x},{y}")
if type_text is not None:
    subprocess.run(adb + ["shell", "input", "text", type_text.replace(" ", "%s")])
    print(f"TYPED '{type_text}'")
