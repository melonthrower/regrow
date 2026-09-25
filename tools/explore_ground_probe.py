"""Standalone probe for one-call GUI target selection plus grounding.

This experiment intentionally does not import the traversal engine, StateGraph,
Router, or runtime scheduling. It sends one bounded Block crop and a small
prompt-local candidate list to the existing screenshot VLM transport, validates
the returned geometry contract, and writes visual diagnostics. It never clicks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GROUNDING_STATUSES = {
    "unique", "ambiguous", "not_visible", "outside_region", "uncertain",
    "disabled",
}
RESOLUTION_STATUSES = {"covered", "semantic_only"}

EXPLORE_GROUND_PROMPT = """\
You are testing one visible functional area of a GUI for graph exploration.
The attached image is only that area's current live crop.

Use only the supplied prompt-local choice IDs. The framework has removed unsafe
targets, but candidate availability can be stale. If a supplied target is
visibly disabled, report grounding_status=disabled and omit geometry.

You may resolve a candidate as:
- covered: a different supplied verified result proves the same functional
  result; cite its evidence_id.
- semantic_only: clicking cannot reveal another functional interface or entry.

Choose at most one unresolved candidate to click. Locate it in THIS CROP and
return one tight bbox plus a safe click point in normalized 0..1000 crop
coordinates. Use grounding_status=unique only when the target is uniquely
visible and enabled. Otherwise use ambiguous, not_visible, outside_region,
uncertain, or disabled and omit geometry. Do not claim page completion or invent
evidence.

Return JSON only:
{"resolved":[{"choice_id":"c1","status":"covered|semantic_only","by_verified":"v0 or empty","reason":"short"}],"action":{"choice_id":"c0","grounding_status":"unique|ambiguous|not_visible|outside_region|uncertain|disabled","bbox_crop_1000":[x0,y0,x1,y1],"click_point_crop_1000":[x,y],"visual_evidence":"short"}}

Context:
{context_json}
"""

FIXED_TARGET_GROUNDING_PROMPT = """\
You are grounding one GUI target that the graph framework has already chosen.
The attached image is the target's current parent-Block crop.

Ground exactly target.choice_id; do not choose a sibling. sibling_text contains
only textual descriptions of other children stored under the same parent node.
When present, use those descriptions contrastively to distinguish the target.
They are not extra images, geometry, or alternative actions.

Return grounding_status=unique with one tight bbox and a safe click point in
normalized 0..1000 CROP coordinates only when the target is visibly unique and
enabled. Otherwise return ambiguous, not_visible, outside_region, uncertain, or
disabled and omit geometry.

Return JSON only:
{"action":{"choice_id":"target id","grounding_status":"unique|ambiguous|not_visible|outside_region|uncertain|disabled","bbox_crop_1000":[x0,y0,x1,y1],"click_point_crop_1000":[x,y],"visual_evidence":"short"}}

Context:
{context_json}
"""

TARGET_REVIEW_PROMPT = """\
Verify one proposed GUI click. The image is a crop with a red proposed bounding
box and a black click crosshair; these marks are not part of the GUI.

Requested target: {target_name}
Model's visual evidence: {visual_evidence}

Return JSON only: {"accepted":true|false,"reason":"short"}
Accept only when the marked point is on the requested control and clicking it
would trigger that control. If the crop lacks enough context, reject it.
"""


DEMO_CASES: dict[str, dict[str, Any]] = {
    "mingle_inbox": {
        "image": "synthetic_mobile_app/reference/inbox_viewport.png",
        "interface": "Chats",
        "block": {
            "description": "visible conversation list",
            "bbox_1000": [34, 124, 966, 926],
        },
        "candidates": [
            {
                "choice_id": "c0",
                "name": "Open Weekend Plan",
                "recent_result": "none",
                "expected_bbox_full_1000": [36, 126, 964, 209],
            },
            {
                "choice_id": "c1",
                "name": "Open Alex Chen chat",
                "recent_result": "none",
                "expected_bbox_full_1000": [36, 209, 964, 292],
            },
        ],
        "verified": [],
    },
}


def _json_object(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    text = str(value or "")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else ""
    if not raw:
        start, end = text.find("{"), text.rfind("}")
        raw = text[start:end + 1] if start >= 0 and end > start else ""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _coord_list(value: Any, length: int) -> list[int] | None:
    if not isinstance(value, list) or len(value) != length:
        return None
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        return None
    if any(item < 0 or item > 1000 for item in value):
        return None
    return list(value)


def validate_response(
    parsed: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
    verified: Sequence[Mapping[str, Any]],
    required_choice_id: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Validate the bounded response without guessing or repairing semantics."""
    clean: dict[str, Any] = {"resolved": [], "action": None}
    if parsed is None:
        return clean, ["response is not a JSON object"]

    candidate_ids = {
        str(item.get("choice_id") or "") for item in candidates
        if str(item.get("choice_id") or "")
    }
    verified_ids = {
        str(item.get("evidence_id") or "") for item in verified
        if str(item.get("evidence_id") or "")
    }
    errors: list[str] = []
    resolved_ids: set[str] = set()

    raw_resolved = parsed.get("resolved") or []
    if not isinstance(raw_resolved, list):
        errors.append("resolved must be a list")
        raw_resolved = []
    for item in raw_resolved:
        if not isinstance(item, Mapping):
            errors.append("each resolved entry must be an object")
            continue
        choice_id = str(item.get("choice_id") or "")
        status = str(item.get("status") or "")
        reason = str(item.get("reason") or "").strip()
        by_verified = str(item.get("by_verified") or "")
        if choice_id not in candidate_ids:
            errors.append(f"resolved references unknown choice_id {choice_id!r}")
            continue
        if choice_id in resolved_ids:
            errors.append(f"choice_id {choice_id!r} is resolved more than once")
            continue
        if status not in RESOLUTION_STATUSES:
            errors.append(f"invalid resolution status for {choice_id!r}")
            continue
        if not reason:
            errors.append(f"resolution reason is missing for {choice_id!r}")
            continue
        if status == "covered" and by_verified not in verified_ids:
            errors.append(f"covered {choice_id!r} cites unknown evidence")
            continue
        if status == "semantic_only" and by_verified:
            errors.append(f"semantic_only {choice_id!r} must not cite evidence")
            continue
        resolved_ids.add(choice_id)
        clean["resolved"].append({
            "choice_id": choice_id,
            "status": status,
            "by_verified": by_verified,
            "reason": reason,
        })

    raw_action = parsed.get("action")
    if raw_action is None:
        if required_choice_id:
            errors.append("fixed-target response must include action")
        return clean, errors
    if not isinstance(raw_action, Mapping):
        return clean, errors + ["action must be an object or null"]

    choice_id = str(raw_action.get("choice_id") or "")
    status = str(raw_action.get("grounding_status") or "")
    evidence = str(raw_action.get("visual_evidence") or "").strip()
    if choice_id not in candidate_ids:
        errors.append(f"action references unknown choice_id {choice_id!r}")
    if required_choice_id and choice_id != required_choice_id:
        errors.append(
            f"action must ground fixed choice_id {required_choice_id!r}")
    if choice_id in resolved_ids:
        errors.append(f"action choice_id {choice_id!r} was also resolved")
    if status not in GROUNDING_STATUSES:
        errors.append("action has invalid grounding_status")
    if not evidence:
        errors.append("action visual_evidence is missing")

    action = {
        "choice_id": choice_id,
        "grounding_status": status,
        "visual_evidence": evidence,
    }
    if status == "unique":
        bbox = _coord_list(raw_action.get("bbox_crop_1000"), 4)
        point = _coord_list(raw_action.get("click_point_crop_1000"), 2)
        if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            errors.append("unique action has invalid bbox_crop_1000")
        if point is None:
            errors.append("unique action has invalid click_point_crop_1000")
        if bbox is not None and point is not None and not (
            bbox[0] <= point[0] <= bbox[2]
            and bbox[1] <= point[1] <= bbox[3]
        ):
            errors.append("click point is outside the proposed bbox")
        if bbox is not None:
            action["bbox_crop_1000"] = bbox
        if point is not None:
            action["click_point_crop_1000"] = point
    elif (raw_action.get("bbox_crop_1000") is not None
          or raw_action.get("click_point_crop_1000") is not None):
        errors.append("non-unique action must omit geometry")
    clean["action"] = action
    return clean, errors


def normalized_bbox_to_pixels(
    bbox: Sequence[int], width: int, height: int,
) -> list[int]:
    x0, y0, x1, y1 = bbox
    return [
        round(x0 / 1000 * width),
        round(y0 / 1000 * height),
        round(x1 / 1000 * width),
        round(y1 / 1000 * height),
    ]


def normalized_point_to_pixels(
    point: Sequence[int], width: int, height: int,
) -> list[int]:
    return [
        round(point[0] / 1000 * width),
        round(point[1] / 1000 * height),
    ]


def crop_geometry(
    image: Image.Image, block_bbox_1000: Sequence[int],
) -> tuple[Image.Image, list[int]]:
    box = normalized_bbox_to_pixels(
        block_bbox_1000, image.width, image.height)
    box[0] = max(0, min(image.width - 1, box[0]))
    box[1] = max(0, min(image.height - 1, box[1]))
    box[2] = max(box[0] + 1, min(image.width, box[2]))
    box[3] = max(box[1] + 1, min(image.height, box[3]))
    return image.crop(tuple(box)), box


def crop_action_to_full(
    action: Mapping[str, Any], crop_box_px: Sequence[int],
    full_size: Sequence[int],
) -> dict[str, Any]:
    """Map crop-normalized geometry to full-image pixels and normalized values."""
    width, height = int(full_size[0]), int(full_size[1])
    x0, y0, x1, y1 = crop_box_px
    crop_width, crop_height = x1 - x0, y1 - y0

    def point_px(point: Sequence[int]) -> list[int]:
        local = normalized_point_to_pixels(point, crop_width, crop_height)
        return [x0 + local[0], y0 + local[1]]

    crop_bbox = action["bbox_crop_1000"]
    crop_point = action["click_point_crop_1000"]
    top_left = point_px(crop_bbox[:2])
    bottom_right = point_px(crop_bbox[2:])
    full_bbox_px = top_left + bottom_right
    full_point_px = point_px(crop_point)
    return {
        **dict(action),
        "bbox_full_px": full_bbox_px,
        "click_point_full_px": full_point_px,
        "bbox_full_1000": [
            round(full_bbox_px[0] / width * 1000),
            round(full_bbox_px[1] / height * 1000),
            round(full_bbox_px[2] / width * 1000),
            round(full_bbox_px[3] / height * 1000),
        ],
        "click_point_full_1000": [
            round(full_point_px[0] / width * 1000),
            round(full_point_px[1] / height * 1000),
        ],
    }


def _candidate_prompt_rows(
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    return [{
        "choice_id": str(item.get("choice_id") or ""),
        "name": str(item.get("name") or ""),
        "recent_result": str(item.get("recent_result") or "none"),
    } for item in candidates]


def build_prompt(case: Mapping[str, Any]) -> str:
    block = case.get("block") if isinstance(case.get("block"), Mapping) else {}
    fixed_choice_id = str(case.get("fixed_target_choice_id") or "")
    if fixed_choice_id:
        candidates = list(case.get("candidates") or [])
        target = next(
            (item for item in candidates
             if str(item.get("choice_id") or "") == fixed_choice_id), None)
        if target is None:
            raise ValueError(
                f"fixed target {fixed_choice_id!r} is not in candidates")
        siblings = []
        if bool(case.get("include_sibling_text")):
            siblings = [{
                "choice_id": str(item.get("choice_id") or ""),
                "description": str(
                    item.get("description") or item.get("name") or ""),
            } for item in candidates
                if str(item.get("choice_id") or "") != fixed_choice_id]
        context = {
            "interface": str(case.get("interface") or ""),
            "block": str(block.get("description") or "functional area"),
            "target": {
                "choice_id": fixed_choice_id,
                "description": str(
                    target.get("description") or target.get("name") or ""),
            },
            "sibling_text": siblings,
        }
        return FIXED_TARGET_GROUNDING_PROMPT.replace(
            "{context_json}",
            json.dumps(context, ensure_ascii=False, separators=(",", ":")),
        )
    context = {
        "interface": str(case.get("interface") or ""),
        "block": str(block.get("description") or "functional area"),
        "candidates": _candidate_prompt_rows(case.get("candidates") or []),
        "verified": list(case.get("verified") or []),
    }
    return EXPLORE_GROUND_PROMPT.replace(
        "{context_json}",
        json.dumps(context, ensure_ascii=False, separators=(",", ":")),
    )


def expected_hit(
    action: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]],
) -> bool | None:
    selected = next((item for item in candidates
                     if str(item.get("choice_id") or "")
                     == str(action.get("choice_id") or "")), None)
    expected = ((selected or {}).get("expected_bbox_full_1000")
                if selected is not None else None)
    point = action.get("click_point_full_1000")
    if not isinstance(expected, list) or not isinstance(point, list):
        return None
    return bool(
        expected[0] <= point[0] <= expected[2]
        and expected[1] <= point[1] <= expected[3]
    )


def annotate(
    image: Image.Image, bbox_px: Sequence[int], point_px: Sequence[int],
    label: str,
) -> Image.Image:
    marked = image.copy().convert("RGB")
    draw = ImageDraw.Draw(marked)
    draw.rectangle(list(bbox_px), outline="red", width=4)
    x, y = point_px
    radius = 9
    draw.line([x - radius, y, x + radius, y], fill="black", width=3)
    draw.line([x, y - radius, x, y + radius], fill="black", width=3)
    draw.text((max(0, bbox_px[0]), max(0, bbox_px[1] - 16)), label,
              fill="red")
    return marked


def _call(agent: Any, prompt: str, image: Image.Image) -> tuple[str, dict[str, Any]]:
    started = time.monotonic()
    result = agent.predict_mm_with_policy(
        prompt, [np.asarray(image.convert("RGB"))], max_attempts=1,
        timeout_seconds=150)
    if isinstance(result, tuple):
        raw = str(result[0] or "")
        prompt_tokens = result[1] if len(result) > 1 else None
        completion_tokens = result[2] if len(result) > 2 else None
        attempts = result[3] if len(result) > 3 else None
    else:
        raw = str(result or "")
        prompt_tokens = completion_tokens = attempts = None
    return raw, {
        "latency_seconds": round(time.monotonic() - started, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "transport_attempts": attempts,
    }


def review_action(
    agent: Any, marked_crop: Image.Image, action: Mapping[str, Any],
    target_name: str,
) -> dict[str, Any]:
    prompt = (TARGET_REVIEW_PROMPT
              .replace("{target_name}", target_name)
              .replace("{visual_evidence}",
                       str(action.get("visual_evidence") or "")))
    raw, transport = _call(agent, prompt, marked_crop)
    parsed = _json_object(raw)
    accepted = (parsed.get("accepted")
                if isinstance(parsed, Mapping) else None)
    valid = isinstance(accepted, bool)
    return {
        "valid": valid,
        "accepted": accepted if valid else False,
        "reason": str((parsed or {}).get("reason") or "") if parsed else "",
        "raw_response": raw,
        "transport": transport,
    }


def run_once(
    agent: Any, case: Mapping[str, Any], image_path: Path,
    output_dir: Path, *, run_review: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    full = Image.open(image_path).convert("RGB")
    block = case.get("block") if isinstance(case.get("block"), Mapping) else {}
    crop, crop_box_px = crop_geometry(full, block.get("bbox_1000") or [])
    crop.save(output_dir / "block_crop.png")

    prompt = build_prompt(case)
    raw, transport = _call(agent, prompt, crop)
    parsed = _json_object(raw)
    clean, errors = validate_response(
        parsed, case.get("candidates") or [], case.get("verified") or [],
        str(case.get("fixed_target_choice_id") or ""))
    result: dict[str, Any] = {
        "status": "ok" if not errors else "invalid_response",
        "input": {
            "image": str(image_path),
            "image_size": list(full.size),
            "crop_box_px": crop_box_px,
            "candidate_count": len(case.get("candidates") or []),
            "prompt_chars": len(prompt),
        },
        "transport": transport,
        "raw_response": raw,
        "parsed_response": parsed,
        "validated_response": clean,
        "validation_errors": errors,
        "expected_hit": None,
        "review": None,
    }
    action = clean.get("action")
    if (not errors and isinstance(action, Mapping)
            and action.get("grounding_status") == "unique"):
        mapped = crop_action_to_full(action, crop_box_px, full.size)
        clean["action"] = mapped
        result["expected_hit"] = expected_hit(
            mapped, case.get("candidates") or [])
        selected = next(
            (item for item in case.get("candidates") or []
             if str(item.get("choice_id") or "")
             == str(mapped.get("choice_id") or "")), {})
        target_name = str(selected.get("name") or mapped.get("choice_id") or "")
        marked_full = annotate(
            full, mapped["bbox_full_px"], mapped["click_point_full_px"],
            target_name)
        marked_full.save(output_dir / "target_overlay_full.png")

        crop_bbox_px = normalized_bbox_to_pixels(
            mapped["bbox_crop_1000"], crop.width, crop.height)
        crop_point_px = normalized_point_to_pixels(
            mapped["click_point_crop_1000"], crop.width, crop.height)
        marked_crop = annotate(crop, crop_bbox_px, crop_point_px, target_name)
        marked_crop.save(output_dir / "target_overlay_crop.png")
        if run_review:
            result["review"] = review_action(
                agent, marked_crop, mapped, target_name)

    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return result


def load_case(name: str, case_path: str) -> dict[str, Any]:
    if case_path:
        data = json.loads(Path(case_path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("case file must contain one JSON object")
        return data
    return json.loads(json.dumps(DEMO_CASES[name]))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Block-local target selection and grounding; never clicks.")
    parser.add_argument("--demo", choices=sorted(DEMO_CASES),
                        default="mingle_inbox")
    parser.add_argument("--case", default="",
                        help="Optional JSON case; overrides --demo contents.")
    parser.add_argument("--image", default="",
                        help="Optional screenshot override.")
    parser.add_argument("--result-dir",
                        default="artifacts/diagnostics/explore_ground_probe")
    parser.add_argument("--model", default="Qwen")
    parser.add_argument("--model-version", default="qwen3.7-plus")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--review", action="store_true",
                        help="Make one extra VLM call on the annotated crop.")
    parser.add_argument("--repeat", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1")
    case = load_case(args.demo, args.case)
    image_value = args.image or str(case.get("image") or "")
    image_path = Path(image_value)
    if not image_path.is_absolute():
        image_path = ROOT / image_path
    if not image_path.is_file():
        raise FileNotFoundError(f"screenshot does not exist: {image_path}")

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent

    agent = GUIGenAgent(
        model=args.model,
        model_version=args.model_version,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        enable_thinking=args.enable_thinking,
        max_retry=1,
    )
    root = Path(args.result_dir)
    if not root.is_absolute():
        root = ROOT / root
    runs = []
    for index in range(1, args.repeat + 1):
        run_dir = root / f"run_{index:02d}"
        result = run_once(
            agent, case, image_path, run_dir, run_review=args.review)
        runs.append({
            "run": index,
            "status": result["status"],
            "choice_id": ((result.get("validated_response") or {}).get(
                "action") or {}).get("choice_id"),
            "expected_hit": result.get("expected_hit"),
            "review_accepted": ((result.get("review") or {}).get("accepted")
                                if result.get("review") else None),
            "latency_seconds": (result.get("transport") or {}).get(
                "latency_seconds"),
        })
    summary = {
        "schema": "gui_rewalk.explore_ground_probe.v1",
        "mode": "standalone_no_click",
        "model": args.model_version,
        "thinking": bool(args.enable_thinking),
        "review_enabled": bool(args.review),
        "runs": runs,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "ok" for item in runs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
