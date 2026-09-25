"""Render small offline node-category visualization demos.

This reads saved exploration artifacts only. It does not connect to a VM or
modify result directories.
"""

from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "_visual_node_category_demo"

SETTINGS_RUN = ROOT / "result_setting_full_graph_20260506_005940_s1000_a5000"
CALC_RUN = ROOT / "result_calculator_strict_direct_20260507_000831"

SETTINGS_NODE = "c7ba26753d5e288b"
CALC_NODE = "fa9a41b657013626"

COLORS: Dict[str, Tuple[int, int, int]] = {
    "navigation": (32, 142, 80),
    "shallow": (54, 106, 220),
    "display": (135, 99, 176),
    "dangerous": (210, 52, 52),
    "nav_control": (20, 150, 170),
    "edge_action": (64, 111, 210),
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def font(size: int = 14) -> ImageFont.ImageFont:
    for name in (
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        p = Path(name)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                pass
    return ImageFont.load_default()


def graph_path(run: Path) -> Path:
    return next((run / "gen_data" / "Doubao" / "graphs").glob("*_graph.json"))


def nodes_dir(run: Path) -> Path:
    return run / "gen_data" / "Doubao" / "0" / "nodes"


def screenshot_path(run: Path, state_id: str) -> Path:
    return nodes_dir(run) / state_id / "screenshot.png"


def llm_path(run: Path, state_id: str) -> Path:
    return nodes_dir(run) / state_id / "llm_unseen_candidates.json"


def node_index(run: Path) -> Dict[str, Any]:
    return load_json(nodes_dir(run) / "node_index.json")


def graph_data(run: Path) -> Dict[str, Any]:
    return load_json(graph_path(run))


def _bbox_from_item(item: Dict[str, Any]) -> Dict[str, int]:
    if "bbox" in item and isinstance(item["bbox"], dict):
        b = item["bbox"]
        return {"x": int(b.get("x", 0)), "y": int(b.get("y", 0)), "w": int(b.get("w", 0)), "h": int(b.get("h", 0))}
    return {
        "x": int(item.get("screen_x", 0)),
        "y": int(item.get("screen_y", 0)),
        "w": int(item.get("width", 0)),
        "h": int(item.get("height", 0)),
    }


def _valid_bbox(b: Dict[str, int]) -> bool:
    return b.get("w", 0) > 2 and b.get("h", 0) > 2


def _item_name(item: Dict[str, Any]) -> str:
    return str(
        item.get("element_name")
        or item.get("vlm_element_name")
        or item.get("name")
        or item.get("element_label")
        or "unnamed"
    )


def _item_category(item: Dict[str, Any]) -> str:
    return str(item.get("category") or item.get("vlm_category") or "unknown").lower()


def category_items(run: Path, state_id: str) -> List[Dict[str, Any]]:
    """Return category records from the saved VLM/a11y classification."""
    path = llm_path(run, state_id)
    if not path.exists():
        return []
    data = load_json(path)

    items: List[Dict[str, Any]] = []
    source = data.get("vlm_discovered_elements") or data.get("llm_unseen_candidates_mapped") or []
    for raw in source:
        cat = _item_category(raw)
        if cat not in {"navigation", "shallow", "display", "dangerous"}:
            continue
        bbox = _bbox_from_item(raw)
        if not _valid_bbox(bbox):
            continue
        items.append(
            {
                "category": cat,
                "name": _item_name(raw),
                "bbox": bbox,
                "score": raw.get("likely_new_page_score", raw.get("vlm_score", "")),
            }
        )

    for raw in data.get("node_local_functions") or []:
        cat = _item_category(raw)
        if cat != "shallow":
            continue
        bbox = _bbox_from_item(raw)
        if not _valid_bbox(bbox):
            continue
        items.append(
            {
                "category": "shallow",
                "name": _item_name(raw),
                "bbox": bbox,
                "score": raw.get("likely_new_page_score", ""),
            }
        )

    controls = data.get("navigation_controls") or {}
    for key, ctrl in controls.items():
        if not isinstance(ctrl, dict) or not ctrl.get("found"):
            continue
        bbox = _bbox_from_item(ctrl)
        if not _valid_bbox(bbox):
            continue
        items.append({"category": "nav_control", "name": f"{key}: {ctrl.get('name') or 'control'}", "bbox": bbox})

    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in items:
        b = item["bbox"]
        key = (item["category"], item["name"], b["x"], b["y"], b["w"], b["h"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _rank_for_demo(item: Dict[str, Any]) -> Tuple[int, int, str]:
    cat_order = {"navigation": 0, "nav_control": 1, "shallow": 2, "display": 3, "dangerous": 4}
    b = item["bbox"]
    return (cat_order.get(item["category"], 9), b["y"], item["name"])


def _filtered_for_demo(items: List[Dict[str, Any]], per_category: Dict[str, int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for item in sorted(items, key=_rank_for_demo):
        cat = item["category"]
        limit = per_category.get(cat, 0)
        counts[cat] = counts.get(cat, 0) + 1
        if counts[cat] <= limit:
            out.append(item)
    return out


def _text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> Tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]




def draw_box(draw: ImageDraw.ImageDraw, item: Dict[str, Any], fnt: ImageFont.ImageFont, label_index: int) -> None:
    b = item["bbox"]
    cat = item["category"]
    color = COLORS.get(cat, (80, 80, 80))
    x0, y0, x1, y1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    draw.rounded_rectangle([x0, y0, x1, y1], radius=5, outline=color, width=4)
    badge = str(label_index)
    tw, th = _text_size(draw, badge, fnt)
    pad = 4
    bx0, by0 = x0 + 3, y0 + 3
    draw.rounded_rectangle(
        [bx0, by0, bx0 + tw + pad * 2, by0 + th + pad * 2],
        radius=4,
        fill=(*color, 230),
        outline=(255, 255, 255),
        width=1,
    )
    draw.text((bx0 + pad, by0 + pad - 1), badge, fill=(255, 255, 255), font=fnt)


def draw_legend(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    counts: Dict[str, int],
    title: str,
    fnt: ImageFont.ImageFont,
    items: List[Dict[str, Any]],
) -> None:
    rows = [title]
    for cat in ("navigation", "nav_control", "shallow", "display", "dangerous"):
        if counts.get(cat):
            rows.append(f"{cat}: {counts[cat]}")
    shown_rows = []
    for i, item in enumerate(items, 1):
        name = item["name"]
        if len(name) > 34:
            name = name[:33] + "."
        shown_rows.append((item["category"], f"{i}. {item['category']} | {name}"))
    box_w = 460
    box_h = 42 + len(rows) * 22 + len(shown_rows) * 20
    draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=8, fill=(255, 255, 255, 235), outline=(185, 194, 207), width=2)
    draw.text((x + 12, y + 10), rows[0], fill=(20, 26, 36), font=fnt)
    yy = y + 36
    for row in rows[1:]:
        cat = row.split(":", 1)[0]
        color = COLORS.get(cat, (80, 80, 80))
        draw.rectangle([x + 14, yy + 3, x + 28, yy + 17], fill=color)
        draw.text((x + 36, yy), row, fill=(20, 26, 36), font=fnt)
        yy += 22
    yy += 8
    small = font(14)
    for cat, row in shown_rows:
        color = COLORS.get(cat, (80, 80, 80))
        draw.text((x + 16, yy), row, fill=color, font=small)
        yy += 20


def render_node(run: Path, state_id: str, output: Path, title: str, per_category: Dict[str, int], legend_xy: Tuple[int, int]) -> Path:
    img = Image.open(screenshot_path(run, state_id)).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    fnt = font(18)
    small = font(15)
    all_items = category_items(run, state_id)
    items = _filtered_for_demo(all_items, per_category)
    for i, item in enumerate(items, 1):
        draw_box(draw, item, small, i)
    counts: Dict[str, int] = {}
    for item in all_items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    draw_legend(draw, legend_xy[0], legend_xy[1], counts, title, fnt, items)
    output.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(output)
    return output


def _fit(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    scale = min(max_w / img.width, max_h / img.height)
    return img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))


def _page_name(node: Dict[str, Any]) -> str:
    labels = node.get("elements") or []
    for elem in labels:
        if elem.get("actionable_ancestor_selected"):
            return str(elem.get("name") or elem.get("text") or "selected")
    for elem in labels:
        if elem.get("tag") == "label" and elem.get("name"):
            if int(elem.get("screen_x", 0)) > 700 and int(elem.get("screen_y", 0)) < 220:
                return str(elem.get("name"))
    return node.get("state_id", "")[:8]


def _draw_arrow(draw: ImageDraw.ImageDraw, start: Tuple[int, int], end: Tuple[int, int], color: Tuple[int, int, int]) -> None:
    draw.line([start, end], fill=color, width=4)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 14
    left = (end[0] - size * math.cos(angle - math.pi / 6), end[1] - size * math.sin(angle - math.pi / 6))
    right = (end[0] - size * math.cos(angle + math.pi / 6), end[1] - size * math.sin(angle + math.pi / 6))
    draw.polygon([end, left, right], fill=color)


def _wrap(text: str, width: int, max_lines: int) -> List[str]:
    lines = textwrap.wrap(" ".join(str(text or "").split()), width=width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines


def render_settings_three_node_overview(output: Path) -> Path:
    graph = graph_data(SETTINGS_RUN)
    idx = node_index(SETTINGS_RUN)
    nodes = {n["state_id"]: n for n in graph["nodes"]}
    ids = [SETTINGS_NODE, "7d426b3b2eb1a315", "e9ad987003a66363"]
    positions = {
        ids[0]: (40, 195),
        ids[1]: (600, 40),
        ids[2]: (600, 410),
    }
    card_w, card_h = 420, 310
    img = Image.new("RGB", (1060, 760), (244, 246, 250))
    draw = ImageDraw.Draw(img)
    fnt = font(15)
    tiny = font(13)
    edge_color = COLORS["edge_action"]

    for sid in ids:
        x, y = positions[sid]
        info = idx[sid]
        node = nodes[sid]
        draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=8, fill=(255, 255, 255), outline=(180, 189, 203), width=2)
        draw.text((x + 14, y + 12), f"{info.get('node_alias')}  {_page_name(node)}", fill=(20, 26, 36), font=fnt)
        draw.text((x + 14, y + 34), sid[:12], fill=(91, 98, 110), font=tiny)
        shot = _fit(Image.open(screenshot_path(SETTINGS_RUN, sid)).convert("RGB"), 390, 225)
        sx = x + (card_w - shot.width) // 2
        sy = y + 62
        img.paste(shot, (sx, sy))
        draw.rectangle([sx, sy, sx + shot.width, sy + shot.height], outline=(210, 214, 221), width=1)
        draw.text((x + 14, y + card_h - 28), f"elements: {info.get('elements_count')}", fill=(70, 76, 88), font=tiny)

    for link in graph["links"]:
        src, dst = link.get("source"), link.get("target")
        if src not in positions or dst not in positions:
            continue
        sx, sy = positions[src]
        dx, dy = positions[dst]
        start = (sx + card_w, sy + card_h // 2)
        end = (dx, dy + card_h // 2)
        _draw_arrow(draw, start, end, edge_color)
        label = str(link.get("element_label", "")).replace("Click ", "")
        desc = link.get("semantic_description", "")
        lines = _wrap(f"{link.get('action_index')}: {label}", 32, 2)
        lines += _wrap(desc, 44, 2)
        lx = (start[0] + end[0]) // 2 - 95
        ly = (start[1] + end[1]) // 2 - 38
        box_h = 16 + len(lines) * 17
        draw.rounded_rectangle([lx - 8, ly - 7, lx + 280, ly + box_h], radius=6, fill=(255, 255, 255), outline=edge_color, width=2)
        for i, line in enumerate(lines):
            draw.text((lx, ly + i * 17), line, fill=(24, 48, 104), font=tiny)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)
    return output


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [
        render_node(
            SETTINGS_RUN,
            SETTINGS_NODE,
            OUT_DIR / "01_settings_node001_categories.png",
            "settings node_001 | saved VLM categories",
            {"navigation": 40, "nav_control": 10, "shallow": 20, "display": 10, "dangerous": 10},
            (1425, 34),
        ),
        render_node(
            CALC_RUN,
            CALC_NODE,
            OUT_DIR / "02_calculator_node001_categories.png",
            "calculator node_001 | saved VLM categories",
            {"navigation": 4, "nav_control": 3, "shallow": 12, "display": 8, "dangerous": 4},
            (520, 34),
        ),
        render_settings_three_node_overview(OUT_DIR / "03_settings_three_node_overview.png"),
    ]
    for out in outputs:
        print(out)


if __name__ == "__main__":
    main()
