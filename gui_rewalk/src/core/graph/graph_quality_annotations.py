"""Render read-only screenshot evidence for graph-quality findings.

The exporter consumes a source ``graph.json`` and an already-produced
``GraphQualityAgent`` report.  It writes copies with overlays into a dedicated
directory; neither the graph nor any source screenshot is opened for writing.
Missing/corrupt evidence is represented as a skipped manifest entry instead of
aborting the export.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


ANNOTATION_SCHEMA = "gui_rewalk_graph_quality_annotations_v1"
_SEVERITIES = frozenset({"ERROR", "WARN"})
_HEADER_HEIGHT = 76
_PANEL_LABEL_HEIGHT = 24
_PANEL_GAP = 6


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _slug(value: Any, fallback: str = "finding") -> str:
    text = re.sub(r"[^0-9A-Za-z]+", "-", str(value or "")).strip("-").lower()
    return (text[:48] or fallback).strip("-")


def _state_id(node: Mapping[str, Any]) -> str:
    return str(node.get("state_id") or node.get("id") or "")


def _safe_child(root: Path, name: str) -> Path:
    """Return a non-symlink child whose resolved path remains below ``root``."""

    if not name or Path(name).name != name:
        raise ValueError(f"unsafe annotation filename: {name!r}")
    candidate = root / name
    if candidate.is_symlink():
        raise ValueError(f"refusing to overwrite symlink: {candidate}")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"annotation path escapes output directory: {candidate}") from exc
    return candidate


def _atomic_png_save(image: Image.Image, path: Path) -> None:
    temporary = _safe_child(path.parent, f".{path.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        image.save(temporary, format="PNG")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json_write(value: Mapping[str, Any], path: Path) -> None:
    temporary = _safe_child(path.parent, f".{path.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> List[Mapping[str, Any]]:
    return [item for item in (value or []) if isinstance(item, Mapping)]


def _point(value: Any) -> Optional[List[float]]:
    if isinstance(value, Mapping):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None


def _bbox(value: Any, *, xywh: bool = False) -> Optional[List[float]]:
    if isinstance(value, Mapping):
        if {"x", "y", "width", "height"} <= set(value):
            value = [value["x"], value["y"], value["width"], value["height"]]
            xywh = True
        elif {"x0", "y0", "x1", "y1"} <= set(value):
            value = [value["x0"], value["y0"], value["x1"], value["y1"]]
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x0, y0, third, fourth = (float(value[index]) for index in range(4))
    except (TypeError, ValueError):
        return None
    if xywh:
        return [x0, y0, x0 + max(0.0, third), y0 + max(0.0, fourth)]
    return [x0, y0, third, fourth]


def _element_bbox(element: Mapping[str, Any]) -> Optional[List[float]]:
    return (
        _bbox(element.get("bbox_xywh"), xywh=True)
        or _bbox(element.get("bbox_xyxy"))
        or _bbox(element.get("bbox"), xywh=True)
    )


def _element_region_bbox(element: Mapping[str, Any]) -> Optional[List[float]]:
    return _bbox(element.get("region_bbox_xywh"), xywh=True) or _bbox(
        element.get("region_bbox")
    )


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _ascii_fallback(text: Any) -> str:
    return str(text or "").encode("ascii", "replace").decode("ascii")


def _draw_text(
    draw: ImageDraw.ImageDraw,
    position: Tuple[int, int],
    text: Any,
    *,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
) -> str:
    rendered = str(text or "")
    try:
        draw.text(position, rendered, font=font, fill=fill)
    except (UnicodeEncodeError, OSError, ValueError):
        rendered = _ascii_fallback(rendered)
        draw.text(position, rendered, font=font, fill=fill)
    return rendered


def _short_message(value: Any, limit: int = 150) -> str:
    message = " ".join(str(value or "").split())
    return message if len(message) <= limit else f"{message[: limit - 3]}..."


def _clamped_rectangle(
    bbox: Sequence[float], width: int, height: int
) -> Optional[List[int]]:
    if len(bbox) < 4:
        return None
    x0, y0, x1, y1 = bbox[:4]
    left = max(0, min(width - 1, int(round(min(x0, x1)))))
    top = max(0, min(height - 1, int(round(min(y0, y1)))))
    right = max(0, min(width - 1, int(round(max(x0, x1)))))
    bottom = max(0, min(height - 1, int(round(max(y0, y1)))))
    if right <= left or bottom <= top:
        return None
    return [left, top, right, bottom]


def _draw_tag(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    *,
    font: ImageFont.ImageFont,
    color: Tuple[int, int, int],
) -> None:
    label = _short_message(text, 64)
    try:
        bounds = draw.textbbox((x, y), label, font=font)
    except (UnicodeEncodeError, OSError, ValueError):
        label = _ascii_fallback(label)
        bounds = draw.textbbox((x, y), label, font=font)
    padding = 3
    draw.rectangle(
        [bounds[0] - padding, bounds[1] - padding, bounds[2] + padding, bounds[3] + padding],
        fill=color,
    )
    _draw_text(draw, (x, y), label, font=font, fill=(10, 10, 10))


def _draw_highlight(
    draw: ImageDraw.ImageDraw,
    highlight: Mapping[str, Any],
    *,
    offset: Tuple[int, int],
    image_size: Tuple[int, int],
    font: ImageFont.ImageFont,
) -> None:
    color = tuple(highlight.get("color") or (255, 230, 0))
    bbox = _bbox(highlight.get("bbox"))
    point = _point(highlight.get("point"))
    if bbox:
        clipped = _clamped_rectangle(bbox, *image_size)
        if clipped:
            shifted = [
                clipped[0] + offset[0],
                clipped[1] + offset[1],
                clipped[2] + offset[0],
                clipped[3] + offset[1],
            ]
            draw.rectangle(shifted, outline=color, width=4)
            _draw_tag(
                draw,
                shifted[0] + 4,
                max(offset[1] + 2, shifted[1] - 20),
                str(highlight.get("label") or highlight.get("kind") or "evidence"),
                font=font,
                color=color,
            )
    if point:
        px = max(0, min(image_size[0] - 1, int(round(point[0])))) + offset[0]
        py = max(0, min(image_size[1] - 1, int(round(point[1])))) + offset[1]
        radius = 9
        draw.ellipse([px - radius, py - radius, px + radius, py + radius], outline=color, width=4)
        draw.line([px - radius - 5, py, px + radius + 5, py], fill=color, width=3)
        draw.line([px, py - radius - 5, px, py + radius + 5], fill=color, width=3)
        _draw_tag(
            draw,
            px + 12,
            max(offset[1] + 2, py - 10),
            str(highlight.get("label") or highlight.get("kind") or "point"),
            font=font,
            color=color,
        )


def _resolved_screenshot(
    node_id: str,
    *,
    node_report: Mapping[str, Any],
    raw_node: Mapping[str, Any],
    graph_path: Path,
) -> Optional[Path]:
    screenshot = _mapping(_mapping(node_report.get("evidence")).get("screenshot"))
    candidates: List[Path] = []
    resolved = screenshot.get("resolved_path")
    if resolved:
        candidates.append(Path(str(resolved)))
    for declared in (screenshot.get("declared_path"), raw_node.get("screenshot_path")):
        if not declared:
            continue
        relative = Path(str(declared).replace("\\", "/"))
        candidates.extend((relative, graph_path.parent / relative, Path.cwd() / relative))
    candidates.extend(
        (
            graph_path.parent / "screenshots" / f"{node_id}.png",
            graph_path.parent / "node_artifacts" / node_id / "screenshot.png",
        )
    )
    seen: set[str] = set()
    for candidate in candidates:
        try:
            path = candidate.expanduser().resolve()
        except OSError:
            continue
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def _load_screenshot(path: Path) -> Optional[Image.Image]:
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB").copy()
    except Exception:
        return None


def _unique_strings(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _finding_node_ids(
    finding: Mapping[str, Any], edge_report: Mapping[str, Any]
) -> List[str]:
    evidence = _mapping(finding.get("evidence"))
    values: List[Any] = [finding.get("node_id")]
    if edge_report:
        values.extend((edge_report.get("source"), edge_report.get("target")))
    else:
        values.extend((finding.get("source"), finding.get("target")))
    for key in ("nodes", "node_ids", "peers"):
        raw = evidence.get(key)
        values.extend(raw if isinstance(raw, (list, tuple, set)) else [])
    values.append(evidence.get("peer"))
    return _unique_strings(values)


def _edge_report_for(
    finding: Mapping[str, Any], edge_reports: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    edge_index = finding.get("edge_index")
    if edge_index is not None:
        for report in edge_reports:
            if report.get("edge_index") == edge_index:
                return report
    source, target = finding.get("source"), finding.get("target")
    if source or target:
        for report in edge_reports:
            if report.get("source") == source and report.get("target") == target:
                return report
    return {}


def _node_highlights(
    finding: Mapping[str, Any], node_report: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    highlights: List[Dict[str, Any]] = []
    evidence = _mapping(finding.get("evidence"))
    elements_evidence = _mapping(_mapping(node_report.get("evidence")).get("elements"))
    elements = _list_of_mappings(elements_evidence.get("items"))
    if finding.get("code") == "node_exploration_incomplete":
        unvisited = {str(item) for item in (evidence.get("unvisited") or [])}
        for element in elements:
            if str(element.get("name") or "") not in unvisited:
                continue
            bbox = _element_bbox(element)
            point = _point(element.get("center")) if not bbox else None
            if bbox or point:
                highlights.append(
                    {
                        "panel": "node",
                        "kind": "unexplored_element",
                        "bbox": bbox,
                        "point": point,
                        "label": f"unexplored: {element.get('name') or '?'}",
                        "color": [90, 255, 90],
                    }
                )
    explicit_element = _mapping(evidence.get("element"))
    if explicit_element:
        bbox = _element_bbox(explicit_element)
        point = _point(explicit_element.get("center")) if not bbox else None
        if bbox or point:
            highlights.append(
                {
                    "panel": "node",
                    "kind": "finding_element",
                    "bbox": bbox,
                    "point": point,
                    "label": str(explicit_element.get("name") or "finding element"),
                    "color": [255, 215, 0],
                }
            )
    return highlights


def _edge_highlights(
    finding: Mapping[str, Any], edge_report: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    report_evidence = _mapping(edge_report.get("evidence"))
    finding_evidence = _mapping(finding.get("evidence"))
    element = _mapping(report_evidence.get("source_element"))
    element_bbox = _bbox(report_evidence.get("source_element_bbox")) or _element_bbox(element)
    region_bbox = (
        _bbox(report_evidence.get("region_bbox"))
        or _bbox(finding_evidence.get("region_bbox"))
        or _element_region_bbox(element)
    )
    resolved_point = _point(report_evidence.get("resolved_point")) or _point(
        finding_evidence.get("executed_point")
    )
    highlights: List[Dict[str, Any]] = []
    if region_bbox:
        highlights.append(
            {
                "panel": "source",
                "kind": "region_bbox",
                "bbox": region_bbox,
                "label": "source region",
                "color": [0, 225, 255],
            }
        )
    if element_bbox:
        highlights.append(
            {
                "panel": "source",
                "kind": "source_element_bbox",
                "bbox": element_bbox,
                "label": f"source: {edge_report.get('element_label') or element.get('name') or '?'}",
                "color": [255, 225, 0],
            }
        )
    if resolved_point:
        highlights.append(
            {
                "panel": "source",
                "kind": "resolved_point",
                "point": resolved_point,
                "label": "resolved click",
                "color": [255, 70, 255],
            }
        )
    return highlights


def _explanation(
    finding: Mapping[str, Any], *, node_ids: Sequence[str], edge_report: Mapping[str, Any]
) -> str:
    message = str(finding.get("message") or "quality finding")
    if edge_report:
        label = str(edge_report.get("element_label") or "?")
        return (
            f"{message} Edge {edge_report.get('edge_index')} follows {label!r}: "
            f"{edge_report.get('source') or '?'} -> {edge_report.get('target') or '?'}; "
            "yellow marks the stored source element, cyan its allowed region, and "
            "magenta the resolved GUI point when available."
        )
    if finding.get("code") == "node_exploration_incomplete":
        names = _mapping(finding.get("evidence")).get("unvisited") or []
        return f"{message} Green boxes identify pending controls: {', '.join(map(str, names))}."
    suffix = f" Related nodes: {', '.join(node_ids)}." if node_ids else ""
    return message + suffix


def _render(
    finding: Mapping[str, Any],
    panels: Sequence[Mapping[str, Any]],
    highlights: Sequence[Mapping[str, Any]],
    *,
    reference: str,
) -> Image.Image:
    widths = [panel["image"].width for panel in panels]
    heights = [panel["image"].height for panel in panels]
    canvas_width = max(480, sum(widths) + _PANEL_GAP * max(0, len(panels) - 1))
    canvas_height = _HEADER_HEIGHT + _PANEL_LABEL_HEIGHT + max(heights)
    canvas = Image.new("RGB", (canvas_width, canvas_height), (238, 238, 238))
    draw = ImageDraw.Draw(canvas)
    severity = str(finding.get("severity") or "WARN").upper()
    header_color = (150, 25, 25) if severity == "ERROR" else (177, 103, 0)
    draw.rectangle([0, 0, canvas_width, _HEADER_HEIGHT - 1], fill=header_color)
    title_font = _load_font(18)
    body_font = _load_font(14)
    label_font = _load_font(13)
    _draw_text(
        draw,
        (12, 8),
        f"{severity} | {finding.get('code') or 'unknown'}",
        font=title_font,
        fill=(255, 255, 255),
    )
    _draw_text(
        draw,
        (12, 34),
        _short_message(
            finding.get("message"), max(24, (canvas_width - 24) // 9)
        ),
        font=body_font,
        fill=(255, 255, 255),
    )
    _draw_text(
        draw,
        (12, 56),
        _short_message(reference, max(24, (canvas_width - 24) // 9)),
        font=label_font,
        fill=(255, 245, 220),
    )

    x = 0
    for panel in panels:
        image = panel["image"]
        role = str(panel["role"])
        draw.rectangle(
            [x, _HEADER_HEIGHT, x + image.width - 1, _HEADER_HEIGHT + _PANEL_LABEL_HEIGHT - 1],
            fill=(42, 42, 42),
        )
        _draw_text(
            draw,
            (x + 7, _HEADER_HEIGHT + 4),
            panel.get("label") or role,
            font=label_font,
            fill=(255, 255, 255),
        )
        y = _HEADER_HEIGHT + _PANEL_LABEL_HEIGHT
        canvas.paste(image, (x, y))
        for highlight in highlights:
            if highlight.get("panel") == role:
                _draw_highlight(
                    draw,
                    highlight,
                    offset=(x, y),
                    image_size=image.size,
                    font=label_font,
                )
        x += image.width + _PANEL_GAP
    return canvas


def export_annotated_evidence(
    graph_path: str | Path,
    report: Mapping[str, Any],
    annotated_dir: str | Path,
) -> Dict[str, Any]:
    """Export one best-effort PNG per ERROR/WARN plus ``manifest.json``.

    The returned value is the same mapping written to the manifest.  Per-finding
    evidence failures are non-fatal and carry ``status=skipped`` with a reason.
    Output names are derived only from a canonical finding hash and safe slugs.
    """

    source_graph = Path(graph_path).expanduser().resolve()
    output_root = Path(annotated_dir).expanduser().resolve()
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"annotated output is not a directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    graph_bytes = source_graph.read_bytes()
    graph_sha256 = hashlib.sha256(graph_bytes).hexdigest()
    try:
        graph_value = json.loads(graph_bytes.decode("utf-8"))
        graph = graph_value if isinstance(graph_value, Mapping) else {}
        graph_parse_error = None
    except Exception as exc:
        graph = {}
        graph_parse_error = f"{type(exc).__name__}: {exc}"

    raw_nodes = {_state_id(node): node for node in _list_of_mappings(graph.get("nodes"))}
    node_reports = {
        str(item.get("node_id") or ""): item
        for item in _list_of_mappings(report.get("nodes"))
        if item.get("node_id")
    }
    edge_reports = _list_of_mappings(report.get("edges"))
    findings = [
        item
        for item in _list_of_mappings(report.get("findings"))
        if str(item.get("severity") or "").upper() in _SEVERITIES
    ]

    entries: List[Dict[str, Any]] = []
    occurrences: Counter[str] = Counter()
    generated = 0
    for finding_index, finding in enumerate(findings):
        finding_key = _canonical_hash(finding)
        occurrences[finding_key] += 1
        occurrence = occurrences[finding_key]
        suffix = "" if occurrence == 1 else f"-{occurrence:02d}"
        filename = (
            f"{_slug(finding.get('severity'))}-{_slug(finding.get('code'))}-"
            f"{finding_key}{suffix}.png"
        )
        edge_report = _edge_report_for(finding, edge_reports)
        node_ids = _finding_node_ids(finding, edge_report)
        entry: Dict[str, Any] = {
            "finding_index": finding_index,
            "finding_key": finding_key,
            "severity": str(finding.get("severity") or "").upper(),
            "code": str(finding.get("code") or ""),
            "scope": str(finding.get("scope") or "graph"),
            "message": str(finding.get("message") or ""),
            "status": "skipped",
            "image": None,
            "node_ids": node_ids,
            "edge": (
                {
                    "edge_index": edge_report.get("edge_index"),
                    "edge_id": edge_report.get("edge_id"),
                    "source": edge_report.get("source"),
                    "target": edge_report.get("target"),
                    "element_label": edge_report.get("element_label"),
                }
                if edge_report
                else None
            ),
            "explanation": _explanation(
                finding, node_ids=node_ids, edge_report=edge_report
            ),
            "highlights": [],
        }
        if not node_ids:
            entry["skip_reason"] = "finding_has_no_node_or_edge_screenshot_reference"
            entries.append(entry)
            continue

        panels: List[Dict[str, Any]] = []
        if edge_report:
            panel_references = [
                (role, node_id)
                for role, node_id in (
                    ("source", str(edge_report.get("source") or "")),
                    ("target", str(edge_report.get("target") or "")),
                )
                if node_id
            ]
        else:
            panel_references = list(zip(("node", "peer"), node_ids[:2]))
        source_paths: List[str] = []
        for role, node_id in panel_references:
            node_report = node_reports.get(node_id, {})
            screenshot_path = _resolved_screenshot(
                node_id,
                node_report=node_report,
                raw_node=raw_nodes.get(node_id, {}),
                graph_path=source_graph,
            )
            if not screenshot_path:
                continue
            image = _load_screenshot(screenshot_path)
            if image is None:
                continue
            panels.append(
                {
                    "role": role,
                    "label": f"{role}: {node_id}",
                    "image": image,
                    "source_path": screenshot_path,
                }
            )
            source_paths.append(str(screenshot_path))
        if not panels:
            entry["skip_reason"] = "referenced_screenshot_missing_or_unreadable"
            entries.append(entry)
            continue

        highlights = (
            _edge_highlights(finding, edge_report)
            if edge_report
            else _node_highlights(finding, node_reports.get(node_ids[0], {}))
        )
        available_roles = {str(panel["role"]) for panel in panels}
        highlights = [item for item in highlights if item.get("panel") in available_roles]
        entry["highlights"] = [
            {key: value for key, value in item.items() if key != "color"}
            for item in highlights
        ]
        entry["source_screenshots"] = source_paths
        destination = _safe_child(output_root, filename)
        if source_graph == destination.resolve(strict=False) or any(
            Path(path).resolve() == destination.resolve(strict=False) for path in source_paths
        ):
            entry["skip_reason"] = "destination_would_overwrite_source_evidence"
            entries.append(entry)
            continue
        reference = (
            f"edge {edge_report.get('edge_index')}: "
            f"{edge_report.get('source')} -> {edge_report.get('target')}"
            if edge_report
            else f"node {node_ids[0]}"
        )
        rendered = _render(
            finding,
            panels,
            highlights,
            reference=reference,
        )
        try:
            _atomic_png_save(rendered, destination)
        except Exception as exc:
            entry["skip_reason"] = f"annotation_write_failed: {type(exc).__name__}: {exc}"
            entries.append(entry)
            continue
        entry["status"] = "generated"
        entry["image"] = destination.relative_to(output_root).as_posix()
        generated += 1
        entries.append(entry)

    manifest: Dict[str, Any] = {
        "schema_version": ANNOTATION_SCHEMA,
        "source_graph": str(source_graph),
        "source_graph_sha256": graph_sha256,
        "graph_parse_error": graph_parse_error,
        "quality_report_schema": report.get("schema_version"),
        "output_directory": str(output_root),
        "finding_count": len(entries),
        "generated_count": generated,
        "skipped_count": len(entries) - generated,
        "findings": entries,
    }
    manifest_path = _safe_child(output_root, "manifest.json")
    _atomic_json_write(manifest, manifest_path)
    return manifest
