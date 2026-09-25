"""Visual-traversal agent role implementation."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image
import io

from .common import _img_arr, _norm_fn, _parse_json
from ..prompts.grounding import (
    ANNOTATION_REVIEW_PROMPT,
    ANNOTATION_REVIEW_WITH_REGIONS_PROMPT,
    TARGET_REVIEW_PROMPT,
)
logger = logging.getLogger(__name__)

_TARGET_REVIEW_CROP_SIDE = 201

class AnnotationReviewer:
    """VLM QA over grounding's annotations: catches wrong / missing / duplicate
    boxes like a human proof-reader (用户 2026-07-06). Called after grounding on a
    NORMAL frame (post-dispatch, so it never wastes a call on an off-app / overlay
    frame). General prompt — the VLM judges 'do these boxes look right', code does
    NOT hard-code 'what is abnormal'. Fails to 'no issues' on any error so it never
    blocks exploration; the engine consumes the result (dedup / log / stop-scroll)."""

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger

    def review(self, som_image, elements) -> Dict[str, Any]:
        """som_image: SoM-labeled frame (np array, numbered boxes matching element
        ids). Returns {"wrong":[id,..], "missing":[{name,where},..],
        "duplicate":[[id,..],..], "ok": bool}. Empty/ok on any error."""
        empty = {"wrong": [], "missing": [], "duplicate": [], "ok": True}
        if self.agent is None or som_image is None or not elements:
            return empty
        try:
            from ..visual_cache import predict_mm_role
            resp, *_ = predict_mm_role(
                self.agent, "annotation_review", ANNOTATION_REVIEW_PROMPT,
                [np.asarray(som_image)], self.ledger)
        except Exception as e:
            logger.warning("annotation reviewer failed: %s", e)
            return empty
        parsed = _parse_json(resp)
        if not isinstance(parsed, dict):
            return empty
        wrong = [v for v in (parsed.get("wrong") or []) if isinstance(v, int)]
        missing = [m for m in (parsed.get("missing") or []) if isinstance(m, dict)]
        dup = [g for g in (parsed.get("duplicate") or []) if isinstance(g, list)]
        ok = not (wrong or missing or dup)
        if not ok:
            logger.info("review: %d wrong, %d missing, %d duplicate-group(s)",
                        len(wrong), len(missing), len(dup))
        return {"wrong": wrong, "missing": missing, "duplicate": dup, "ok": ok}

    def review_target(self, screenshot_bytes: bytes, target: Any,
                      stored_target: Any) -> Dict[str, Any]:
        """Verify the exact click point for one named target; fail closed."""
        empty = {"accepted": False, "reason": "review_unavailable"}
        if self.agent is None or not screenshot_bytes or target is None:
            return empty
        try:
            original = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
            cx, cy = [int(v) for v in target.center]
            if not (0 <= cx < original.width and 0 <= cy < original.height):
                return {"accepted": False, "reason": "click_point_out_of_frame"}
            radius = _TARGET_REVIEW_CROP_SIDE // 2
            left, top = cx - radius, cy - radius
            right = left + _TARGET_REVIEW_CROP_SIDE
            bottom = top + _TARGET_REVIEW_CROP_SIDE
            click_crop = Image.new(
                "RGB", (_TARGET_REVIEW_CROP_SIDE, _TARGET_REVIEW_CROP_SIDE),
                (127, 127, 127))
            source_box = (
                max(0, left), max(0, top),
                min(original.width, right), min(original.height, bottom),
            )
            source = original.crop(source_box)
            click_crop.paste(source, (max(0, -left), max(0, -top)))
            prompt = TARGET_REVIEW_PROMPT.format(
                name=str(getattr(stored_target, "name", "")),
            )
            from ..visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "target_review", prompt,
                [np.asarray(original), np.asarray(click_crop)], self.ledger,
                max_attempts=1)
        except Exception as exc:
            logger.warning("target reviewer failed: %s", exc)
            return {"accepted": False, "reason": f"review_error:{exc}"}
        parsed = _parse_json(response)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("accepted"), bool):
            return {"accepted": False, "reason": "invalid_review_response",
                    "raw_response": str(response or "")}
        return {"accepted": bool(parsed["accepted"]),
                "reason": str(parsed.get("reason") or ""),
                "raw_response": str(response or "")}

    def review_with_regions(self, som_image, elements, regions) -> Dict[str, Any]:
        """[2026-07-08 用户] 合并质检:一次 VLM 调用同时核 元素框(wrong/missing/duplicate)
        + 区块分割(region_missing/region_split/region_merge)。跑在区块分割后、命名前,
        让质检员能在身份 mint 前指出"漏了 content 面板"这类分裂根因。
        regions: [{role, note, names:[..]}] 当前分割的文本描述。
        返回在 review() 基础上多 region_missing / region_split / region_merge 三键。"""
        empty = {"wrong": [], "missing": [], "duplicate": [], "ok": True,
                 "region_missing": [], "region_split": [], "region_merge": []}
        if self.agent is None or som_image is None or not elements:
            return empty
        # 区块列表文本化(role + 备注 + 成员前3),VLM 对照截图判分割
        if regions:
            lines = []
            for r in regions:
                nm = "、".join((r.get("names") or [])[:3])
                lines.append(f"  - {r.get('role','?')}: {r.get('note','') or ''}"
                             + (f" (含 {nm}…)" if nm else ""))
            regions_txt = "\n".join(lines)
        else:
            regions_txt = "  (未能划出任何区块)"
        prompt = ANNOTATION_REVIEW_WITH_REGIONS_PROMPT.format(regions=regions_txt)
        try:
            from ..visual_cache import predict_mm_role
            resp, *_ = predict_mm_role(
                self.agent, "merged_review", prompt,
                [np.asarray(som_image)], self.ledger)
        except Exception as e:
            logger.warning("merged reviewer failed: %s", e)
            return empty
        parsed = _parse_json(resp)
        if not isinstance(parsed, dict):
            return empty
        wrong = [v for v in (parsed.get("wrong") or []) if isinstance(v, int)]
        missing = [m for m in (parsed.get("missing") or []) if isinstance(m, dict)]
        dup = [g for g in (parsed.get("duplicate") or []) if isinstance(g, list)]
        rmiss = [m for m in (parsed.get("region_missing") or []) if isinstance(m, dict)]
        rsplit = [s for s in (parsed.get("region_split") or []) if isinstance(s, str)]
        rmerge = [g for g in (parsed.get("region_merge") or []) if isinstance(g, list)]
        ok = not (wrong or missing or dup or rmiss or rsplit or rmerge)
        if not ok:
            logger.info("merged review: %dw %dm %ddup | region: %d漏 %d该拆 %d该并",
                        len(wrong), len(missing), len(dup),
                        len(rmiss), len(rsplit), len(rmerge))
        return {"wrong": wrong, "missing": missing, "duplicate": dup, "ok": ok,
                "region_missing": rmiss, "region_split": rsplit,
                "region_merge": rmerge}
