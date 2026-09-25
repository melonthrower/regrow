"""Opt-in page-map -> Region localization -> crop inventory experiment."""

from __future__ import annotations

import io
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from .prompts.block_inventory import (
    PAGE_MAP_PROMPT,
    build_region_inventory_prompt,
    build_region_localization_prompt,
)
from .visual_cache import predict_mm_role


def _json_object(response: Any) -> Optional[Dict[str, Any]]:
    text = str(response or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        value = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except Exception:
            return None
    return value if isinstance(value, dict) else None


def _optional_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _normalized_bbox(value: Any) -> Optional[List[int]]:
    try:
        if not isinstance(value, list) or len(value) != 4:
            return None
        if any(isinstance(item, bool) or float(item) != int(float(item))
               for item in value):
            return None
        x0, y0, x1, y1 = [int(float(item)) for item in value]
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            return None
        return [x0, y0, x1, y1]
    except (TypeError, ValueError):
        return None


class BlockFirstInventoryExperiment:
    """Run the isolated three-call perception experiment on one saved frame."""

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger

    @staticmethod
    def _image(screenshot_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")

    def discover(self, screenshot_bytes: bytes, *,
                 force_refresh: bool = False) -> Dict[str, Any]:
        """Build a geometry-free semantic page map."""
        image = self._image(screenshot_bytes)
        response, *_ = predict_mm_role(
            self.agent, "semantic_page_map", PAGE_MAP_PROMPT,
            [np.asarray(image)], self.ledger, max_attempts=1,
            timeout_seconds=150, use_response_cache=not force_refresh)
        payload = _json_object(response)
        result: Dict[str, Any] = {
            "status": "invalid_response",
            "raw_response": str(response or ""),
            "interface_name": "",
            "regions": [],
        }
        if not payload or not isinstance(payload.get("regions"), list):
            return result
        regions: List[Dict[str, Any]] = []
        seen = set()
        for raw in payload["regions"]:
            if not isinstance(raw, dict):
                continue
            region_id = str(raw.get("region_id") or "").strip()
            name = str(raw.get("name") or "").strip()
            description = str(raw.get("description") or "").strip()
            if not region_id or region_id in seen or not name or not description:
                continue
            seen.add(region_id)
            regions.append({
                "region_id": region_id,
                "name": name,
                "description": description,
            })
        interface_name = str(payload.get("interface_name") or "").strip()
        result.update({
            "status": "ok" if regions else "no_valid_regions",
            "interface_name": interface_name,
            "regions": regions,
        })
        return result

    @staticmethod
    def choose(regions: List[Dict[str, Any]], selector: str) -> Optional[Dict[str, Any]]:
        wanted = str(selector or "").strip().casefold()
        if not wanted:
            return None
        by_id = [region for region in regions
                 if str(region.get("region_id") or "").casefold() == wanted]
        if len(by_id) == 1:
            return by_id[0]
        by_name = [region for region in regions
                   if str(region.get("name") or "").casefold() == wanted]
        return by_name[0] if len(by_name) == 1 else None

    def locate(self, screenshot_bytes: bytes, discovery: Dict[str, Any],
               region: Dict[str, Any], *,
               force_refresh: bool = False) -> Dict[str, Any]:
        """Locate one selected Region without asking for any elements."""
        image = self._image(screenshot_bytes)
        context = dict(region)
        context["interface_name"] = discovery.get("interface_name")
        prompt = build_region_localization_prompt(context)
        response, *_ = predict_mm_role(
            self.agent, "semantic_region_localization", prompt,
            [np.asarray(image)], self.ledger, max_attempts=1,
            timeout_seconds=150, use_response_cache=not force_refresh)
        payload = _json_object(response)
        expected = str(region.get("region_id") or "")
        bbox = _normalized_bbox((payload or {}).get("bbox_1000"))
        valid = bool(
            payload and payload.get("found") is True and bbox
            and str(payload.get("region_id") or "") == expected)
        return {
            "status": "ok" if valid else "not_found",
            "region_id": expected,
            "found": bool(valid),
            "bbox_1000": bbox,
            "scrollable": _optional_bool((payload or {}).get("scrollable")),
            "reason": str((payload or {}).get("reason") or "").strip(),
            "raw_response": str(response or ""),
        }

    @staticmethod
    def crop(image: Image.Image, localization: Dict[str, Any]) -> Image.Image:
        x0, y0, x1, y1 = localization["bbox_1000"]
        left = max(0, int(math.floor(x0 * image.width / 1000)))
        top = max(0, int(math.floor(y0 * image.height / 1000)))
        right = min(image.width, int(math.ceil(x1 * image.width / 1000)))
        bottom = min(image.height, int(math.ceil(y1 * image.height / 1000)))
        return image.crop((left, top, right, bottom))

    @staticmethod
    def _validate_function_entries(
            rows: Any) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
        accepted: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        seen = set()
        if not isinstance(rows, list):
            return accepted, [{
                "reason": "function_entries is not a list", "item": rows}]
        for raw in rows:
            reason = ""
            if not isinstance(raw, dict):
                reason = "function entry is not an object"
            else:
                entry_id = str(raw.get("entry_id") or "").strip()
                target = str(raw.get("target") or "").strip()
                if not entry_id or entry_id in seen:
                    reason = "missing or duplicate entry_id"
                elif not target:
                    reason = "missing target"
            if reason:
                rejected.append({"reason": reason, "item": raw})
                continue
            seen.add(entry_id)
            accepted.append({
                "entry_id": entry_id,
                "target": target,
            })
        return accepted, rejected

    def inventory(self, screenshot_bytes: bytes, discovery: Dict[str, Any],
                  region: Dict[str, Any], localization: Dict[str, Any], *,
                  force_refresh: bool = False,
                  image_mode: str = "crop") -> Tuple[Dict[str, Any], Image.Image]:
        """Discover function entries in one located Region."""
        image = self._image(screenshot_bytes)
        crop = self.crop(image, localization)
        if image_mode not in {"crop", "full", "context_crop"}:
            raise ValueError(
                "image_mode must be 'crop', 'full', or 'context_crop'")
        request_images = (
            [image, crop]
            if image_mode == "context_crop"
            else ([image] if image_mode == "full"
                  else [crop])
        )
        saved_input = image if image_mode == "full" else crop
        context = dict(region)
        context.update({
            "interface_name": discovery.get("interface_name"),
            "bbox_1000": localization.get("bbox_1000"),
            "scrollable": localization.get("scrollable"),
            "peer_regions": [
                {
                    "region_id": str(candidate.get("region_id") or ""),
                    "name": str(candidate.get("name") or ""),
                    "description": str(candidate.get("description") or ""),
                }
                for candidate in discovery.get("regions") or []
                if str(candidate.get("region_id") or "") !=
                str(region.get("region_id") or "")
            ],
        })
        result = self.inventory_views(
            request_images, context, force_refresh=force_refresh,
            image_mode=image_mode)
        result.update({
            "interface_name": discovery.get("interface_name"),
            "region": dict(region),
            "localization": dict(localization),
        })
        return result, saved_input

    def inventory_views(
        self, request_images: List[Image.Image], context: Dict[str, Any], *,
        force_refresh: bool = False, image_mode: str = "long_region",
    ) -> Dict[str, Any]:
        """Apply the Region-local function-entry contract to prepared views."""
        if not request_images:
            return {
                "status": "invalid_request",
                "image_mode": image_mode,
                "input_image_count": 0,
                "function_entries": [],
                "rejected_function_entries": [],
                "raw_response": "",
            }
        prompt = build_region_inventory_prompt(context, image_mode=image_mode)
        from .visual_cache import predict_mm_role as predict_region_inventory
        response, *_ = predict_region_inventory(
            self.agent, "semantic_region_inventory", prompt,
            [np.asarray(value) for value in request_images],
            self.ledger, max_attempts=1, timeout_seconds=150,
            use_response_cache=not force_refresh)
        payload = _json_object(response)
        expected = str(context.get("region_id") or "")
        structurally_valid = bool(
            payload and str(payload.get("region_id") or "") == expected
            and isinstance(payload.get("function_entries"), list))
        function_entries, rejected = self._validate_function_entries(
            payload.get("function_entries") if structurally_valid else None)
        status = "invalid_response"
        if structurally_valid:
            status = "partial" if rejected else "ok"
        return {
            "status": status,
            "image_mode": image_mode,
            "input_image_count": len(request_images),
            "function_entries": function_entries,
            "rejected_function_entries": rejected,
            "raw_response": str(response or ""),
        }


__all__ = ["BlockFirstInventoryExperiment"]
