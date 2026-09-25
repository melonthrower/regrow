"""Seed an Android emulator with realistic user data so DATA-DRIVEN apps (Files,
Photos, Music, Contacts, Messages) have content to traverse instead of empty-
state screens ("No items" / "Once you start a new conversation…").

WHY: the AVD is a fresh device. Files / Photos / Messages / Contacts therefore
collapse to 5-6 empty-state nodes — not a traversal bug, just no data. This is
the android_world-style initialization (it ships exactly this idea in
``task_evals/utils/user_data_generation.py`` + ``utils/contacts_utils.py``).

This module reuses android_world's CONVENTIONS (its per-directory filename sets,
realistic names) but drives the device over plain adb, so it has no dependency
on android_world's AsyncEnv / proto chain and runs as a robust pre-traversal
step. Files land in the standard MediaStore dirs and are media-scanned so they
show up in Files / Photos / Music immediately.

Contacts/SMS are intentionally NOT here: those are best added through
android_world's own ``contacts_utils.add_contact`` (INSERT intent + Save click),
which our AndroidGUIGenEnv already supports via its ``aw_controller`` — call it
as an in-process hook. See seed_contacts() note at the bottom.

Usage:
  python tools/seed_device.py --serial emulator-5582 [--adb ~/android-sdk/platform-tools/adb]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

# android_world's EMULATOR_DIRECTORIES convention (a realistic subset per dir).
SEED = {
    "Download":  ["budget_2024.pdf", "meeting_notes.txt", "recipe.txt", "invoice_march.pdf"],
    "Documents": ["todo_list.txt", "project_plan.md", "reading_list.txt"],
    "DCIM/Camera": ["holiday_photos.jpg", "birthday_party.jpg", "mountain_hike.jpg"],
    "Pictures":  ["nature_pics.jpg", "road_trip.jpg", "screenshot_app.png"],
    "Music":     ["morning_playlist.txt"],  # real mp3 optional; a listed file is enough
}
SAMPLE_TEXT = {
    "meeting_notes.txt": "Team sync 10am.\n- Ship traversal seeding\n- Review graph audit\n- Plan next sprint",
    "recipe.txt": "Pasta:\n200g spaghetti\n2 cloves garlic\nolive oil, chili, parsley",
    "todo_list.txt": "1. Seed device\n2. Re-run Files/Messaging\n3. Compare node counts",
    "project_plan.md": "# Project Plan\n\n## Phase 1\nTrustworthy graph\n\n## Phase 2\nCapability graph",
    "reading_list.txt": "- Designing Data-Intensive Applications\n- The Pragmatic Programmer",
    "morning_playlist.txt": "1. Song A\n2. Song B\n3. Song C",
}


def adb(serial: str, adb_path: str, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([adb_path, "-s", serial, *args],
                          capture_output=True, text=True, **kw)


def _make_image(path: str, label: str) -> None:
    colors = [(70, 130, 180), (180, 100, 70), (90, 160, 110), (150, 110, 170)]
    img = Image.new("RGB", (1080, 1440), colors[hash(label) % len(colors)])
    d = ImageDraw.Draw(img)
    d.text((60, 700), label, fill=(255, 255, 255))
    img.save(path, "PNG" if path.lower().endswith(".png") else "JPEG")


def _make_pdf(path: str, title: str) -> None:
    # minimal single-page PDF (valid enough to be listed AND opened by a viewer)
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 60>>stream\nBT /F1 24 Tf 72 700 Td ("
        + title.encode() + b") Tj ET\nendstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )
    with open(path, "wb") as f:
        f.write(body)


def _make_local(tmp: str, name: str) -> str:
    p = os.path.join(tmp, name)
    ext = name.lower().rsplit(".", 1)[-1]
    if ext in ("jpg", "jpeg", "png"):
        _make_image(p, name)
    elif ext == "pdf":
        _make_pdf(p, name)
    else:  # txt / md / anything text-ish
        with open(p, "w", encoding="utf-8") as f:
            f.write(SAMPLE_TEXT.get(name, f"Sample file: {name}\n"))
    return p


def seed_files(serial: str, adb_path: str) -> int:
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for subdir, names in SEED.items():
            remote_dir = f"/sdcard/{subdir}"
            adb(serial, adb_path, "shell", "mkdir", "-p", remote_dir)
            for name in names:
                local = _make_local(tmp, name)
                remote = f"{remote_dir}/{name}"
                r = adb(serial, adb_path, "push", local, remote)
                if r.returncode == 0:
                    n += 1
                    # media-scan so it shows in Photos/Music (Files lists it anyway)
                    adb(serial, adb_path, "shell", "am", "broadcast", "-a",
                        "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                        "-d", f"file://{remote}")
                else:
                    print(f"  push FAILED {remote}: {r.stderr.strip()[:80]}")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True, help="e.g. emulator-5582")
    ap.add_argument("--adb", default=os.path.expanduser("~/android-sdk/platform-tools/adb"))
    args = ap.parse_args()

    dev = adb(args.serial, args.adb, "get-state")
    if dev.returncode != 0 or "device" not in dev.stdout:
        raise SystemExit(f"{args.serial} not ready: {dev.stdout}{dev.stderr}")

    n = seed_files(args.serial, args.adb)
    print(f"seeded {n} files onto {args.serial}")
    # quick verify
    for d in ("Download", "DCIM/Camera", "Pictures"):
        ls = adb(args.serial, args.adb, "shell", "ls", f"/sdcard/{d}")
        print(f"  /sdcard/{d}: {ls.stdout.strip().splitlines()}")


if __name__ == "__main__":
    main()
