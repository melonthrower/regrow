"""Render per-EDGE action-inspection images for a human-like quality check.

The counts in graph.json can't tell you whether a click LANDED on the button it
claims. This tool makes that visible: for each edge it draws the recorded click
point on the SOURCE node screenshot, captions it with the claimed element label,
and pastes the TARGET node screenshot beside it — so an inspector (human or VLM)
can judge two things by LOOKING:

  1. POSITION — is the click marker actually on the labelled element, or on blank
     space / the status bar / a different row? (the RC1 coord-desync mis-click)
  2. RESULT  — does the page we landed on (target) match what that button should
     open? (clicking "Network" but landing on "Digital Wellbeing")

Below-the-fold elements (scroll_steps>0) were clicked AFTER scrolling, so their
marker on the top-frame screenshot is in a DIFFERENT frame and is flagged
UNRELIABLE — judge those by label-vs-result consistency instead of the dot.

Usage:
  python tools/annotate_actions.py <run_dir_with_graph.json> -o <out_dir> [--max N]
Writes out_dir/edge_<i>_<src8>-<tgt8>.png and prints a manifest.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(sz: int):
    for p in ("arial.ttf", "DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def _shot(run_dir: Path, nid: str):
    for c in (run_dir / "node_artifacts" / nid / "screenshot.png",
              run_dir / "screenshots" / f"{nid}.png"):
        if c.exists():
            return c
    return None


def _elements(run_dir: Path, nid: str):
    p = run_dir / "node_artifacts" / nid / "elements.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _scroll_steps_near(els, x, y):
    """scroll_steps of the element whose center is nearest the click (or 0)."""
    best, bd = 0, 1e18
    for e in els:
        c = e.get("center") or [0, 0]
        d = (c[0] - x) ** 2 + (c[1] - y) ** 2
        if d < bd:
            bd, best = d, int(e.get("scroll_steps", 0) or 0)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("_action_inspect"))
    ap.add_argument("--max", type=int, default=0, help="cap number of edges (0=all)")
    args = ap.parse_args()

    gpath = args.path / "graph.json"
    if not gpath.exists():
        f = list(args.path.rglob("graph.json"))
        gpath = f[0] if f else gpath
    run_dir = gpath.parent
    data = json.loads(gpath.read_text(encoding="utf-8"))
    edges = data.get("edges", data.get("links", []))
    args.out.mkdir(parents=True, exist_ok=True)

    f_lbl = _font(20)
    f_small = _font(16)
    manifest = []
    n = 0
    for i, e in enumerate(edges):
        s, t = e.get("source"), e.get("target")
        sp, tp = _shot(run_dir, s), _shot(run_dir, t)
        if not sp:
            continue
        a = e.get("action", {})
        p = a.get("parameters", a) if isinstance(a, dict) else {}
        x, y = p.get("x"), p.get("y")
        label = (e.get("element_label") or e.get("semantic_description") or "(unnamed)").strip()
        ss = _scroll_steps_near(_elements(run_dir, s), x or 0, y or 0)

        src = Image.open(sp).convert("RGB")
        sw, sh = src.size
        d = ImageDraw.Draw(src)
        # click marker
        if x is not None and y is not None:
            r = max(14, sw // 28)
            col = (255, 60, 60) if ss == 0 else (255, 170, 0)  # orange = unreliable
            d.ellipse([x - r, y - r, x + r, y + r], outline=col, width=5)
            d.line([x - r - 8, y, x + r + 8, y], fill=col, width=3)
            d.line([x, y - r - 8, x, y + r + 8], fill=col, width=3)
        # caption band at top
        cap = f"CLICK @({x},{y})  ->  \"{label}\""
        warn = "" if ss == 0 else f"   [scroll v{ss}: marker is TOP-frame, UNRELIABLE - judge by result]"
        d.rectangle([0, 0, sw, 60], fill=(0, 0, 0))
        d.text((8, 6), cap, fill=(255, 255, 255), font=f_lbl)
        if warn:
            d.text((8, 36), warn.strip(), fill=(255, 200, 0), font=f_small)

        tgt = Image.open(tp).convert("RGB") if tp else Image.new("RGB", (sw, sh), (40, 40, 40))
        # scale target to same height
        th = sh
        tw = int(tgt.size[0] * th / tgt.size[1])
        tgt = tgt.resize((tw, th))
        dt = ImageDraw.Draw(tgt)
        dt.rectangle([0, 0, tw, 36], fill=(0, 0, 0))
        dt.text((8, 6), f"-> landed: {t[:8] if t else '??'}", fill=(150, 230, 150), font=f_small)

        gap = 30
        canvas = Image.new("RGB", (sw + gap + tw, sh), (20, 20, 22))
        canvas.paste(src, (0, 0))
        canvas.paste(tgt, (sw + gap, 0))
        da = ImageDraw.Draw(canvas)
        da.text((sw + 4, sh // 2 - 10), "==>", fill=(255, 255, 255), font=f_lbl)

        out = args.out / f"edge_{i:03d}_{(s or '')[:8]}-{(t or '')[:8]}.png"
        canvas.save(out)
        manifest.append({"file": out.name, "label": label, "click": [x, y],
                         "scroll_steps": ss, "src": s, "tgt": t,
                         "marker_reliable": ss == 0})
        n += 1
        if args.max and n >= args.max:
            break

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {n} action-inspection images to {args.out}")
    print(f"  reliable-marker (top-frame) edges: {sum(1 for m in manifest if m['marker_reliable'])}")
    print(f"  scrolled (marker unreliable) edges: {sum(1 for m in manifest if not m['marker_reliable'])}")
    print(f"manifest: {args.out / 'manifest.json'}")


if __name__ == "__main__":
    main()
