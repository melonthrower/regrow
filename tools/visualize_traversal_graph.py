"""Render a static traversal graph from saved graph exploration artifacts.

Input can be either a nodes directory containing ``node_index.json`` and
``transitions.ndjson``, or a run directory that contains them below
``gen_data/<model>/<task>/nodes``.
"""

from __future__ import annotations

import argparse
import json
import math
import textwrap
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw, ImageFont


CARD_W = 420
CARD_H = 310
THUMB_W = 390
THUMB_H = 225
X_GAP = 140
Y_GAP = 60
MARGIN = 40


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_ndjson(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _find_nodes_dir(path: Path) -> Path:
    path = path.resolve()
    if (path / "node_index.json").exists():
        return path
    candidates = sorted(path.rglob("node_index.json"))
    if not candidates:
        raise FileNotFoundError(f"Cannot find node_index.json under {path}")
    return candidates[0].parent


def _node_dir(nodes_dir: Path, state_id: str, node_info: Dict[str, Any]) -> Path:
    state_dir = node_info.get("state_dir") or state_id
    return nodes_dir / state_dir


def _load_elements(node_dir: Path, graph_nodes: Dict[str, Dict[str, Any]], state_id: str) -> List[Dict[str, Any]]:
    elements_path = node_dir / "elements.json"
    if elements_path.exists():
        return _load_json(elements_path)
    return graph_nodes.get(state_id, {}).get("elements", [])


def _load_screenshot(nodes_dir: Path, node_dir: Path, node_info: Dict[str, Any]) -> Image.Image:
    candidates: List[Path] = []
    meta_path = node_dir / "state_meta.json"
    if meta_path.exists():
        meta = _load_json(meta_path)
        shot = meta.get("screenshot_path")
        if shot:
            candidates.append((nodes_dir.parents[3] / shot).resolve() if len(nodes_dir.parents) >= 4 else Path(shot))
            candidates.append((Path.cwd() / shot).resolve())
    if node_info.get("screenshot_path"):
        candidates.append((Path.cwd() / node_info["screenshot_path"]).resolve())
    candidates.append(node_dir / "screenshot.png")

    for candidate in candidates:
        if candidate.exists():
            return Image.open(candidate).convert("RGB")
    return Image.new("RGB", (THUMB_W, THUMB_H), (80, 80, 80))


def _selected_page_name(elements: Iterable[Dict[str, Any]]) -> str:
    labels = list(elements)
    for elem in labels:
        extra = elem.get("extra") or {}
        if elem.get("actionable_ancestor_selected") or extra.get("actionable_ancestor_selected"):
            return str(elem.get("name") or elem.get("text") or extra.get("actionable_ancestor_name") or "selected")

    header_labels = [
        elem for elem in labels
        if elem.get("tag") == "label"
        and int(elem.get("screen_y", 9999) or 9999) < 210
        and int(elem.get("screen_x", 0) or 0) > 700
        and (elem.get("name") or elem.get("text"))
    ]
    if header_labels:
        return str(header_labels[-1].get("name") or header_labels[-1].get("text"))
    return "unknown"


def _fit_image(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    scale = min(max_w / img.width, max_h / img.height)
    size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(size)


def _wrap(text: str, width: int = 46, max_lines: int = 3) -> List[str]:
    text = " ".join(str(text or "").split())
    if not text:
        return []
    lines = textwrap.wrap(text, width=width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines


def _graph_nodes_from_json(nodes_dir: Path) -> Dict[str, Dict[str, Any]]:
    graph_path = nodes_dir.parent.parent / "graphs" / "0_graph.json"
    if not graph_path.exists():
        return {}
    data = _load_json(graph_path)
    return {
        node.get("state_id", ""): node
        for node in data.get("nodes", [])
        if node.get("state_id")
    }


def _graph_links_from_json(nodes_dir: Path) -> List[Dict[str, Any]]:
    graph_path = nodes_dir.parent.parent / "graphs" / "0_graph.json"
    if not graph_path.exists():
        return []
    data = _load_json(graph_path)
    links: List[Dict[str, Any]] = []
    for link in data.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        src = link.get("source")
        dst = link.get("target")
        if not src or not dst:
            continue
        row = dict(link)
        row["src"] = src
        row["dst"] = dst
        row.setdefault("from_graph_json", True)
        links.append(row)
    return links


def _merge_transition_rows(
    transitions: List[Dict[str, Any]],
    graph_links: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged = list(transitions)
    seen = {
        (
            str(row.get("src") or ""),
            str(row.get("dst") or ""),
            str(row.get("element_id") or ""),
            str(row.get("element_label") or ""),
        )
        for row in merged
    }
    for link in graph_links:
        key = (
            str(link.get("src") or ""),
            str(link.get("dst") or ""),
            str(link.get("element_id") or ""),
            str(link.get("element_label") or ""),
        )
        if key in seen:
            for row in merged:
                row_key = (
                    str(row.get("src") or ""),
                    str(row.get("dst") or ""),
                    str(row.get("element_id") or ""),
                    str(row.get("element_label") or ""),
                )
                if row_key == key:
                    row["semantic_deferred"] = bool(
                        row.get("semantic_deferred")
                        or link.get("semantic_deferred", False)
                    )
                    row.setdefault("from_graph_json", False)
                    break
            continue
        seen.add(key)
        merged.append(link)
    return merged


def _compute_levels(node_ids: List[str], transitions: List[Dict[str, Any]]) -> Dict[str, int]:
    outgoing: Dict[str, List[str]] = defaultdict(list)
    incoming_count = {node_id: 0 for node_id in node_ids}
    for tr in transitions:
        src = tr.get("src")
        dst = tr.get("dst")
        if src in incoming_count and dst in incoming_count:
            outgoing[src].append(dst)
            incoming_count[dst] += 1

    roots = [node_id for node_id in node_ids if incoming_count.get(node_id, 0) == 0]
    if not roots and node_ids:
        roots = [node_ids[0]]

    levels: Dict[str, int] = {}
    q = deque((root, 0) for root in roots)
    while q:
        node_id, level = q.popleft()
        if node_id in levels and levels[node_id] <= level:
            continue
        levels[node_id] = level
        for dst in outgoing.get(node_id, []):
            q.append((dst, level + 1))

    fallback_level = max(levels.values(), default=0) + 1
    for node_id in node_ids:
        levels.setdefault(node_id, fallback_level)
    return levels


def _draw_arrow(draw: ImageDraw.ImageDraw, start: Tuple[int, int], end: Tuple[int, int], color: Tuple[int, int, int]) -> None:
    draw.line([start, end], fill=color, width=3)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 12
    left = (
        end[0] - size * math.cos(angle - math.pi / 6),
        end[1] - size * math.sin(angle - math.pi / 6),
    )
    right = (
        end[0] - size * math.cos(angle + math.pi / 6),
        end[1] - size * math.sin(angle + math.pi / 6),
    )
    draw.polygon([end, left, right], fill=color)


def _draw_dashed_arrow(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    color: Tuple[int, int, int],
) -> None:
    x1, y1 = start
    x2, y2 = end
    length = max(1.0, math.hypot(x2 - x1, y2 - y1))
    dash = 16.0
    gap = 10.0
    t = 0.0
    while t < length:
        t2 = min(length, t + dash)
        sx = x1 + (x2 - x1) * (t / length)
        sy = y1 + (y2 - y1) * (t / length)
        ex = x1 + (x2 - x1) * (t2 / length)
        ey = y1 + (y2 - y1) * (t2 / length)
        draw.line([(sx, sy), (ex, ey)], fill=color, width=3)
        t += dash + gap
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 12
    left = (
        end[0] - size * math.cos(angle - math.pi / 6),
        end[1] - size * math.sin(angle - math.pi / 6),
    )
    right = (
        end[0] - size * math.cos(angle + math.pi / 6),
        end[1] - size * math.sin(angle + math.pi / 6),
    )
    draw.polygon([end, left, right], fill=color)


def render(nodes_dir: Path, output: Path) -> Path:
    nodes_dir = _find_nodes_dir(nodes_dir)
    node_index = _load_json(nodes_dir / "node_index.json")
    transitions = _read_ndjson(nodes_dir / "transitions.ndjson")
    transitions = _merge_transition_rows(transitions, _graph_links_from_json(nodes_dir))
    graph_nodes = _graph_nodes_from_json(nodes_dir)

    node_ids = list(node_index.keys())
    levels = _compute_levels(node_ids, transitions)
    grouped: Dict[int, List[str]] = defaultdict(list)
    for node_id in node_ids:
        grouped[levels[node_id]].append(node_id)

    max_level = max(grouped.keys(), default=0)
    max_rows = max((len(v) for v in grouped.values()), default=1)
    canvas_w = MARGIN * 2 + (max_level + 1) * CARD_W + max_level * X_GAP
    canvas_h = MARGIN * 2 + max_rows * CARD_H + max(0, max_rows - 1) * Y_GAP
    img = Image.new("RGB", (canvas_w, canvas_h), (245, 246, 248))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    positions: Dict[str, Tuple[int, int]] = {}
    page_names: Dict[str, str] = {}

    for level, ids in grouped.items():
        x = MARGIN + level * (CARD_W + X_GAP)
        total_h = len(ids) * CARD_H + max(0, len(ids) - 1) * Y_GAP
        y = MARGIN + max(0, (canvas_h - MARGIN * 2 - total_h) // 2)
        for state_id in ids:
            info = node_index[state_id]
            ndir = _node_dir(nodes_dir, state_id, info)
            elements = _load_elements(ndir, graph_nodes, state_id)
            page_name = _selected_page_name(elements)
            page_names[state_id] = page_name
            positions[state_id] = (x, y)

            draw.rounded_rectangle([x, y, x + CARD_W, y + CARD_H], radius=8, fill=(255, 255, 255), outline=(190, 196, 205), width=2)
            alias = info.get("node_alias", "")
            title = f"{alias}  {page_name}".strip()
            draw.text((x + 14, y + 12), title, fill=(20, 26, 36), font=font)
            draw.text((x + 14, y + 30), state_id[:12], fill=(90, 96, 108), font=font)

            shot = _load_screenshot(nodes_dir, ndir, info)
            thumb = _fit_image(shot, THUMB_W, THUMB_H)
            tx = x + (CARD_W - thumb.width) // 2
            ty = y + 56
            img.paste(thumb, (tx, ty))
            draw.rectangle([tx, ty, tx + thumb.width, ty + thumb.height], outline=(210, 214, 220), width=1)

            element_count = info.get("elements_count", len(elements))
            draw.text((x + 14, y + CARD_H - 28), f"elements: {element_count}", fill=(70, 76, 88), font=font)
            y += CARD_H + Y_GAP

    edge_color = (64, 111, 210)
    inferred_color = (126, 87, 194)
    deferred_color = (230, 126, 34)
    for tr in transitions:
        src = tr.get("src")
        dst = tr.get("dst")
        if src not in positions or dst not in positions:
            continue
        sx, sy = positions[src]
        dx, dy = positions[dst]
        start = (sx + CARD_W, sy + CARD_H // 2)
        end = (dx, dy + CARD_H // 2)
        if src == dst:
            continue
        action = tr.get("action") or {}
        is_inferred = isinstance(action, dict) and action.get("type") == "inferred"
        is_deferred = bool(tr.get("semantic_deferred"))
        color = deferred_color if is_deferred else inferred_color if is_inferred else edge_color
        if is_deferred:
            _draw_dashed_arrow(draw, start, end, color)
        else:
            _draw_arrow(draw, start, end, color)
        label = tr.get("element_label") or tr.get("action", {}).get("action_type") or "action"
        label = str(label).replace("Click ", "")
        prefix = ""
        if is_inferred:
            prefix += "[inferred] "
        if is_deferred:
            prefix += "[deferred] "
        desc = tr.get("semantic_description", "")
        lines = _wrap(f"{prefix}{tr.get('action_index', '')}: {label}", width=28, max_lines=2)
        lines += _wrap(desc, width=42, max_lines=2)
        lx = (start[0] + end[0]) // 2 - 130
        ly = (start[1] + end[1]) // 2 - 28
        box_h = max(24, 14 * len(lines) + 8)
        draw.rounded_rectangle([lx - 6, ly - 4, lx + 270, ly + box_h], radius=6, fill=(255, 255, 255), outline=color, width=1)
        for i, line in enumerate(lines):
            draw.text((lx, ly + i * 14), line, fill=color, font=font)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Run directory or nodes directory")
    parser.add_argument("-o", "--output", type=Path, default=Path("_traversal_graph.png"))
    args = parser.parse_args()
    out = render(args.path, args.output)
    print(out)


if __name__ == "__main__":
    main()
