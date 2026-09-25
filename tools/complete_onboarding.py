"""Click through the first-run onboarding of the seeded 3rd-party apps so they
open directly to their data (Simple Gallery permission, Retro Music permission +
library scan, Markor 5-page intro) — otherwise a -read-only baseline shows these
apps stuck on onboarding every boot and the traversal explores the intro instead
of the seeded data.

Pure adb + uiautomator: each round, dump the UI, tap the first button whose text/
content-desc matches a common onboarding keyword; if none, swipe left (pager
intros). Generic, no per-app coordinates.

Usage:  python tools/complete_onboarding.py <serial>   e.g. emulator-5590
"""
import os
import re
import subprocess
import sys
import time

serial = sys.argv[1] if len(sys.argv) > 1 else "emulator-5590"
adb = os.path.expanduser("~/android-sdk/platform-tools/adb")

# Lower-cased. Order matters: prefer the in-app, least-destructive grant
# ("media only" over "all files", which would bounce to a system settings page).
KEYWORDS = [
    "media only", "while using", "allow", "got it", "continue", "next", "agree",
    "i agree", "accept", "get started", "start", "finish", "done", "skip", "ok",
    "yes", "grant", "enable",
]


def sh(*a):
    return subprocess.run([adb, "-s", serial, *a], capture_output=True, text=True)


def dump_xml():
    sh("shell", "uiautomator", "dump", "/sdcard/o.xml")
    return sh("shell", "cat", "/sdcard/o.xml").stdout


def tap_first_button(xml):
    """Tap the first node whose text/desc matches a keyword; return what/where."""
    for m in re.finditer(
            r'(?:text|content-desc)="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml):
        label = m.group(1).strip().lower()
        if not label or len(label) > 24:
            continue
        if any(label == k or label.startswith(k) or (" " + k + " ") in (" " + label + " ")
               for k in KEYWORDS):
            x = (int(m.group(2)) + int(m.group(4))) // 2
            y = (int(m.group(3)) + int(m.group(5))) // 2
            sh("shell", "input", "tap", str(x), str(y))
            return label, (x, y)
    return None, None


APPS = [
    ("gallery", "com.simplemobiletools.gallery.pro"),
    ("music", "code.name.monkey.retromusic"),
    ("markor", "net.gsantner.markor"),
]

for name, pkg in APPS:
    print(f"--- {name} ---")
    sh("shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(5)
    for i in range(8):
        xml = dump_xml()
        label, _ = tap_first_button(xml)
        if label:
            print(f"  tapped '{label}'")
            time.sleep(2)
            continue
        # no button — likely a pager intro (Markor). swipe to next page.
        sh("shell", "input", "swipe", "950", "1000", "120", "1000", "300")
        time.sleep(1.5)
        # after swiping, a final page may have a finish button
        label2, _ = tap_first_button(dump_xml())
        if label2:
            print(f"  (after swipe) tapped '{label2}'")
            time.sleep(2)
    sh("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)

print("onboarding pass done")
