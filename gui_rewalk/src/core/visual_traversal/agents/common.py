"""Shared parsing and image helpers for visual-traversal agent roles."""

from __future__ import annotations

import io
import json
import re
from typing import Any, Optional

import numpy as np
from PIL import Image
def _img_arr(screenshot_bytes: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(screenshot_bytes)).convert("RGB"))

def _parse_json(raw: str) -> Optional[Any]:
    """Tolerant JSON extraction (handles ```json fences and bare objects)."""
    if not raw:
        return None
    text = raw.strip()
    fenced = []
    for match in re.finditer(
            r"```(?:json)?\s*(.*?)\s*```", text,
            re.DOTALL | re.IGNORECASE):
        try:
            fenced.append(json.loads(match.group(1)))
        except (json.JSONDecodeError, ValueError):
            continue
    if fenced:
        # Some models emit a draft JSON, reconsider it in prose, then emit the
        # corrected answer.  The final complete fenced object is authoritative.
        return fenced[-1]
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

def _norm_fn(name: str) -> str:
    """Normalise a button name into a semantic function key for dedup."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())
