#!/usr/bin/env python
"""Extract dropdown option values from a saved Calculator Preferences node.

This is a diagnostic script.  It does not click the GUI and does not call a
VLM.  It parses the saved a11y tree for hidden/attached list-box option
values, then optionally uses the node's VLM unmatched visual discoveries to
attach human labels such as "Angle units" and "Word size".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


STATE_NS = "https://accessibility.ubuntu.example.org/ns/state"


def _state_true(node: ET.Element, key: str) -> bool:
    return node.get(f"{{{STATE_NS}}}{key}", "false") == "true"


def _node_texts(node: ET.Element) -> List[str]:
    values: List[str] = []
    for child in node.iter():
        name = (child.get("name") or "").strip()
        text = (child.text or "").strip()
        if name:
            values.append(name)
        elif text:
            values.append(text)
    return values


def _first_text(node: ET.Element) -> str:
    for value in _node_texts(node):
        if value:
            return value
    return ""


def _dedupe_keep_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        value = value.strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _find_target_frame(root: ET.Element, frame_name: str) -> Optional[ET.Element]:
    if frame_name:
        for node in root.iter():
            if node.tag == "frame" and (node.get("name") or "") == frame_name:
                return node
    active_modal_frames = [
        node
        for node in root.iter()
        if node.tag == "frame" and _state_true(node, "active") and _state_true(node, "modal")
    ]
    if active_modal_frames:
        return active_modal_frames[0]
    active_frames = [
        node
        for node in root.iter()
        if node.tag == "frame" and _state_true(node, "active")
    ]
    return active_frames[0] if active_frames else None


def extract_listboxes(a11y_path: Path, frame_name: str = "Preferences") -> List[Dict[str, Any]]:
    root = ET.parse(a11y_path).getroot()
    frame = _find_target_frame(root, frame_name)
    if frame is None:
        raise RuntimeError(f"Could not find frame {frame_name!r} in {a11y_path}")

    lists: List[Dict[str, Any]] = []
    for index, listbox in enumerate(frame.iter("list-box")):
        options = []
        for item in listbox.iter("list-item"):
            value = _first_text(item)
            if value:
                options.append(value)
        options = _dedupe_keep_order(options)
        if options:
            lists.append({
                "index": index,
                "options": options,
                "option_count": len(options),
            })
    return lists


def _clean_label(raw: str) -> str:
    label = raw.strip()
    label = re.sub(r"\s+(dropdown|drop-down|combo box|combobox|selector|chooser)\b", "", label, flags=re.I)
    return label.strip(" :-")


def load_visual_dropdown_labels(report_path: Path) -> List[Dict[str, Any]]:
    if not report_path.exists():
        return []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidates = report.get("unmatched_visual_candidates", [])
    if not isinstance(candidates, list):
        return []

    rows: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = " ".join(
            str(item.get(key, "") or "").lower()
            for key in ("element_name", "control_label", "control_type", "reason")
        )
        if not any(token in text for token in ("dropdown", "drop-down", "combo", "selector", "chooser")):
            continue
        if any(token in text for token in ("close", "increase", "decrease")):
            continue
        bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
        label = (
            str(item.get("control_label") or "").strip()
            or _clean_label(str(item.get("element_name") or ""))
        )
        rows.append({
            "label": label,
            "current_value": str(item.get("current_value") or "").strip(),
            "control_type": str(item.get("control_type") or "dropdown").strip() or "dropdown",
            "bbox": {
                "x": int(bbox.get("x", 0) or 0),
                "y": int(bbox.get("y", 0) or 0),
                "w": int(bbox.get("w", 0) or 0),
                "h": int(bbox.get("h", 0) or 0),
            },
            "source": "unmatched_visual_candidates",
        })
    return sorted(rows, key=lambda row: (row["bbox"]["y"], row["bbox"]["x"]))


def pair_labels_with_options(
    labels: List[Dict[str, Any]],
    lists: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    paired: List[Dict[str, Any]] = []
    count = max(len(labels), len(lists))
    for index in range(count):
        label = labels[index] if index < len(labels) else {}
        options = lists[index] if index < len(lists) else {}
        paired.append({
            "control_label": label.get("label", f"dropdown_{index + 1}"),
            "current_value": label.get("current_value", ""),
            "control_type": label.get("control_type", "dropdown"),
            "options": options.get("options", []),
            "option_count": options.get("option_count", 0),
            "visual_bbox": label.get("bbox", {}),
            "a11y_list_index": options.get("index", index),
        })
    return paired


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--node-dir",
        type=Path,
        default=Path("result_calculator_list_values_20260510_112100/gen_data/Doubao/0/nodes/0040f2a0b9c9c284"),
        help="Saved graph node directory containing a11y.xml and optionally llm_unseen_candidates.json.",
    )
    parser.add_argument("--a11y", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--frame", default="Preferences")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    a11y_path = args.a11y or args.node_dir / "a11y.xml"
    report_path = args.report or args.node_dir / "llm_unseen_candidates.json"
    lists = extract_listboxes(a11y_path, args.frame)
    labels = load_visual_dropdown_labels(report_path)
    paired = pair_labels_with_options(labels, lists)

    payload = {
        "node_dir": str(args.node_dir),
        "a11y": str(a11y_path),
        "report": str(report_path) if report_path.exists() else "",
        "frame": args.frame,
        "dropdowns": paired,
        "raw_a11y_listboxes": lists,
        "visual_dropdown_labels": labels,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Frame: {args.frame}")
    print(f"A11y list-boxes found: {len(lists)}")
    print(f"Visual dropdown labels found: {len(labels)}")
    print()
    for item in paired:
        current = item["current_value"] or "unknown"
        options = ", ".join(item["options"]) if item["options"] else "(none)"
        print(f"- {item['control_label']}: current={current}; options=[{options}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
