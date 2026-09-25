#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Synthesize GNOME-style crash dialogs to test the crash_dialog axis (real
apport crashes are hard to force in the docker VM). These are clearly SYNTHETIC
and reported as such — they test whether the VLM keys on crash-dialog text/chrome.
Saved into /tmp/abn_frames/ alongside the real captures.
"""

import os
from PIL import Image, ImageDraw, ImageFont

OUT = "/tmp/abn_frames"


def font(sz):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def make(name, title, body, bg=(38, 38, 40)):
    W, H = 1280, 800
    img = Image.new("RGB", (W, H), bg)  # dim desktop backdrop
    d = ImageDraw.Draw(img)
    # dialog box
    dw, dh = 560, 240
    x0, y0 = (W - dw) // 2, (H - dh) // 2
    d.rectangle([x0, y0, x0 + dw, y0 + dh], fill=(246, 245, 244),
                outline=(180, 180, 180), width=2)
    # title bar
    d.rectangle([x0, y0, x0 + dw, y0 + 40], fill=(222, 221, 218))
    d.text((x0 + 16, y0 + 12), title, fill=(40, 40, 40), font=font(15))
    # body
    d.text((x0 + 24, y0 + 70), body, fill=(30, 30, 30), font=font(16))
    # buttons
    d.rectangle([x0 + dw - 230, y0 + dh - 56, x0 + dw - 130, y0 + dh - 20],
                fill=(228, 228, 228), outline=(170, 170, 170))
    d.text((x0 + dw - 210, y0 + dh - 48), "Cancel", fill=(30, 30, 30), font=font(14))
    d.rectangle([x0 + dw - 120, y0 + dh - 56, x0 + dw - 20, y0 + dh - 20],
                fill=(53, 132, 228), outline=(40, 110, 200))
    d.text((x0 + dw - 104, y0 + dh - 48), "Report", fill=(255, 255, 255), font=font(14))
    img.save(os.path.join(OUT, name))
    print("[synth]", name)


def main():
    os.makedirs(OUT, exist_ok=True)
    make("synthgimp__abnormal__crash_dialog__report.png",
         "System program problem detected",
         "GIMP closed unexpectedly.\nDo you want to report the problem?")
    make("synthcalc__abnormal__crash_dialog__stopped.png",
         "Problem Report",
         "The application Calculator has stopped\nresponding and was closed.")


if __name__ == "__main__":
    main()
