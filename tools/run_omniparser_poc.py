"""Standalone OmniParser PoC: YOLO icon detect + Florence-2 caption.

Goal: see if OmniParser's icon-caption model can fill the a11y `name=""`
gap on our Logs run (currently 38% un-grounded after Qwen+name-lookup).

Bypasses `get_som_labeled_img` because it crashes when called with empty
`ocr_bbox` (line 532 zips None with []). We compose the pipeline ourselves
using its lower-level building blocks:
    predict_yolo   -> xyxy in pixel space
    remove_overlap_new -> drop overlapping yolo boxes
    get_parsed_content_icon -> Florence-2 captions per crop

Output: writes nodes/<sid>/omniparser_icons.json. Does NOT modify any
existing project file; this is purely an analysis artifact alongside the
existing llm_unseen_candidates*.json files.

First run will download Florence-2-base processor (~50MB) from HuggingFace.
The fine-tuned caption weights themselves are already local.

Usage:
  python tools/run_omniparser_poc.py
  python tools/run_omniparser_poc.py --run <path-to-Doubao/0>
  python tools/run_omniparser_poc.py --box-threshold 0.05 --iou-threshold 0.7
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from gui_rewalk.env.utils import (  # noqa: E402
    get_parsed_content_icon,
    get_yolo_model,
    predict_yolo,
    remove_overlap_new,
)


def _install_flash_attn_stub() -> None:
    """Stub flash_attn so transformers' `check_imports` static parse of
    Florence-2's modeling.py passes. Must be called AFTER transformers has
    finished its own init (so its `find_spec('flash_attn')` runs cleanly
    with no module present). The stub is never actually called because we
    pass attn_implementation='eager'.
    """
    import importlib.machinery
    import types
    if "flash_attn" in sys.modules:
        return
    spec = importlib.machinery.ModuleSpec("flash_attn", loader=None)
    stub = types.ModuleType("flash_attn")
    stub.__spec__ = spec
    stub.__version__ = "0.0.0-stub"
    stub.flash_attn_func = None
    stub.flash_attn_varlen_func = None
    sys.modules["flash_attn"] = stub
    for sub in ("flash_attn.bert_padding", "flash_attn.flash_attn_interface"):
        sm = types.ModuleType(sub)
        sm.__spec__ = importlib.machinery.ModuleSpec(sub, loader=None)
        sm.index_first_axis = None
        sm.pad_input = None
        sm.unpad_input = None
        sys.modules[sub] = sm


def _load_florence2_eager(model_path: str, device: str):
    """Inline Florence-2 loader using attn_implementation='eager'. Project
    `get_caption_model_processor` doesn't expose this knob, so we replicate
    it here for the PoC.
    """
    # Import transformers first so its own flash_attn presence check runs
    # with the genuine "not installed" answer.
    from transformers import AutoProcessor, AutoModelForCausalLM, AutoConfig
    # Now stub flash_attn for the dynamic-module static-import check.
    _install_flash_attn_stub()
    # Florence-2 references newer transformers helpers that this older
    # version is missing. Stub them — eager attn means none are called.
    import transformers.utils as _tu
    if not hasattr(_tu, "is_flash_attn_greater_or_equal_2_10"):
        _tu.is_flash_attn_greater_or_equal_2_10 = lambda *a, **kw: False
    if not hasattr(_tu, "is_flash_attn_2_available"):
        _tu.is_flash_attn_2_available = lambda *a, **kw: False
    import transformers.modeling_attn_mask_utils as _mu
    if not hasattr(_mu, "_prepare_4d_attention_mask_for_sdpa"):
        _mu._prepare_4d_attention_mask_for_sdpa = lambda *a, **kw: None
    if not hasattr(_mu, "_prepare_4d_causal_attention_mask_for_sdpa"):
        _mu._prepare_4d_causal_attention_mask_for_sdpa = lambda *a, **kw: None

    processor = AutoProcessor.from_pretrained(
        "microsoft/Florence-2-base", trust_remote_code=True
    )
    dtype = torch.float16 if device != "cpu" else torch.float32
    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
    config._attn_implementation = "eager"
    if hasattr(config, "vision_config"):
        config.vision_config._attn_implementation = "eager"
    if hasattr(config, "text_config"):
        config.text_config._attn_implementation = "eager"
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        config=config,
        torch_dtype=dtype,
        trust_remote_code=True,
    ).to(device)
    return {"model": model, "processor": processor}


DEFAULT_RUN = REPO_ROOT / "result_logs_0427_v3" / "gen_data" / "Doubao" / "0"
YOLO_WEIGHTS = REPO_ROOT / "omniparser" / "weights" / "icon_detect" / "model.pt"
CAPTION_WEIGHTS = REPO_ROOT / "omniparser" / "weights" / "icon_caption_florence"
OUT_FILENAME = "omniparser_icons.json"


def parse_screenshot(
    image: Image.Image,
    yolo_model,
    caption_mp,
    box_threshold: float,
    iou_threshold: float,
    batch_size: int,
) -> List[Dict[str, Any]]:
    """YOLO + Florence-2 caption. Returns list of dicts with pixel bboxes."""
    image = image.convert("RGB")
    w, h = image.size
    image_np = np.asarray(image)

    # 1) YOLO detect — xyxy in pixel space
    xyxy, conf, _ = predict_yolo(
        model=yolo_model,
        image=image,
        box_threshold=box_threshold,
        imgsz=(h, w),
        scale_img=False,
        iou_threshold=0.1,
        yolo_print=False,
    )
    if len(xyxy) == 0:
        return []

    # 2) Convert to [0,1] ratio xyxy and wrap as elements for overlap removal
    xyxy_ratio = xyxy / torch.tensor([w, h, w, h], device=xyxy.device)
    xyxy_list = xyxy_ratio.cpu().tolist()
    conf_list = conf.cpu().tolist()
    icon_elems = [
        {"type": "icon", "bbox": box, "interactivity": True, "content": None, "_score": s}
        for box, s in zip(xyxy_list, conf_list)
    ]

    # 3) Remove overlapping yolo boxes (smaller wins). No OCR boxes.
    filtered = remove_overlap_new(boxes=icon_elems, iou_threshold=iou_threshold, ocr_bbox=None)
    if not filtered:
        return []

    # The overlap pass drops the _score key; rebuild a score lookup by bbox identity.
    # Since remove_overlap_new keeps bbox values intact, match on tuple.
    score_by_box = {tuple(e["bbox"]): e.get("_score", 0.0) for e in icon_elems}

    # 4) Caption every box. starting_idx=0 because we have no OCR rows in front.
    boxes_tensor = torch.tensor([e["bbox"] for e in filtered])
    captions = get_parsed_content_icon(
        boxes_tensor,
        starting_idx=0,
        image_source=image_np,
        caption_model_processor=caption_mp,
        prompt=None,
        batch_size=batch_size,
    )

    # 5) Build final list with pixel xywh
    out: List[Dict[str, Any]] = []
    for elem, cap in zip(filtered, captions):
        x0, y0, x1, y1 = elem["bbox"]
        px = int(round(x0 * w))
        py = int(round(y0 * h))
        pw = max(1, int(round((x1 - x0) * w)))
        ph = max(1, int(round((y1 - y0) * h)))
        out.append({
            "bbox": [px, py, pw, ph],
            "caption": (cap or "").strip(),
            "score": round(float(score_by_box.get(tuple(elem["bbox"]), 0.0)), 4),
            "source": elem.get("source", "box_yolo_content_yolo"),
        })
    return out


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, default=DEFAULT_RUN)
    p.add_argument("--yolo-weights", type=Path, default=YOLO_WEIGHTS)
    p.add_argument("--caption-weights", type=Path, default=CAPTION_WEIGHTS)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--box-threshold", type=float, default=0.05,
                   help="YOLO conf threshold (gradio_demo default = 0.05)")
    p.add_argument("--iou-threshold", type=float, default=0.7,
                   help="Overlap removal IoU threshold")
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--force", action="store_true", help="Re-run even if output exists")
    p.add_argument("--limit", type=int, default=0, help="Stop after N nodes (0 = all)")
    args = p.parse_args(argv)

    if not args.yolo_weights.exists():
        print(f"ERROR: YOLO weights not found at {args.yolo_weights}")
        return 2
    if not args.caption_weights.exists():
        print(f"ERROR: caption weights dir not found at {args.caption_weights}")
        return 2

    nodes_dir = args.run / "nodes"
    screenshots_dir = args.run / "screenshots"
    if not nodes_dir.exists():
        print(f"ERROR: nodes dir not found: {nodes_dir}")
        return 2

    print(f"Run:    {args.run}")
    print(f"Device: {args.device}")
    print(f"YOLO:   {args.yolo_weights}")
    print(f"Caption:{args.caption_weights}")
    print(f"thresholds: box={args.box_threshold}  iou={args.iou_threshold}")
    print()

    print("Loading YOLO ...", flush=True)
    t0 = time.time()
    yolo_model = get_yolo_model(str(args.yolo_weights))
    print(f"  loaded in {time.time() - t0:.1f}s")

    print("Loading Florence-2 caption (eager attn) ...", flush=True)
    t0 = time.time()
    caption_mp = _load_florence2_eager(
        model_path=str(args.caption_weights),
        device=args.device,
    )
    print(f"  loaded in {time.time() - t0:.1f}s")
    print()

    sids = sorted(p.name for p in nodes_dir.iterdir() if p.is_dir())
    if args.limit:
        sids = sids[: args.limit]

    n_done = 0
    n_skipped = 0
    total_icons = 0
    total_time = 0.0
    for sid in sids:
        shot = screenshots_dir / f"{sid}.png"
        out_path = nodes_dir / sid / OUT_FILENAME
        if not shot.exists():
            continue
        if out_path.exists() and not args.force:
            try:
                existing = json.load(open(out_path, encoding="utf-8"))
                n_icons = len(existing.get("icons", []))
                print(f"  [{sid[:8]}] cached  ({n_icons} icons)  -> {out_path.name}")
                n_skipped += 1
                total_icons += n_icons
                continue
            except Exception:
                pass

        try:
            img = Image.open(shot)
        except Exception as e:
            print(f"  [{sid[:8]}] cannot open screenshot: {e}")
            continue

        t0 = time.time()
        try:
            icons = parse_screenshot(
                img, yolo_model, caption_mp,
                box_threshold=args.box_threshold,
                iou_threshold=args.iou_threshold,
                batch_size=args.batch_size,
            )
        except Exception as e:
            print(f"  [{sid[:8]}] FAILED: {e}")
            continue
        dt = time.time() - t0
        total_time += dt
        total_icons += len(icons)

        out = {
            "state_id": sid,
            "screenshot": str(shot.relative_to(args.run.parent)) if shot.is_relative_to(args.run.parent) else str(shot),
            "screenshot_size": list(img.size),
            "icons": icons,
            "_meta": {
                "model": "florence2",
                "yolo_weights": str(args.yolo_weights.name),
                "box_threshold": args.box_threshold,
                "iou_threshold": args.iou_threshold,
                "elapsed_s": round(dt, 2),
                "n_icons": len(icons),
            },
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        n_done += 1
        print(f"  [{sid[:8]}] {dt:5.1f}s  icons={len(icons):>3}  -> {out_path.name}")

    print()
    if n_done:
        print(f"Done: {n_done} new, {n_skipped} cached. avg {total_time / max(1, n_done):.1f}s/img")
    print(f"Total icons across {n_done + n_skipped} nodes: {total_icons}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
