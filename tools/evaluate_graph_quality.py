#!/usr/bin/env python3
"""Offline quality evaluation for a screenshot-only GUI-ReWalk graph.

This complements ``graph_lint.py``.  It never calls a VLM or changes a graph:
it checks structural invariants, screenshot evidence, navigation landing labels,
coverage, and common signs that a desktop/system/error screen polluted a run.

Usage:
  python -B tools/evaluate_graph_quality.py graph.json
  python -B tools/evaluate_graph_quality.py graph.json --json-out quality.json \
      --html-out quality.html --fail-on error
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

try:
    from tools.graph_lint import lint
except ModuleNotFoundError:  # Direct ``python tools/evaluate_graph_quality.py``.
    from graph_lint import lint


SUSPICIOUS_TERMS = (
    "desktop", "crash", "error", "failed", "problem report", "report a problem",
    "system program problem", "authentication required", "update available",
    "software updater", "session", "gnome shell", "oops", "traceback",
)


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return graph.get("nodes") or graph.get("states") or []


def _sid(node: dict[str, Any]) -> str:
    return str(node.get("state_id") or node.get("id") or "")


def _normalize(text: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").lower())


def _find_screenshot(raw: Any, graph_path: Path, workspace: Path) -> Path | None:
    if not raw:
        return None
    raw_path = Path(str(raw).replace("\\", "/"))
    candidates = [raw_path, workspace / raw_path, graph_path.parent / raw_path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _dhash(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("L").resize((9, 8))
        pixels = list(image.getdata())
    bits = []
    for row in range(8):
        offset = row * 9
        bits.extend("1" if pixels[offset + col] > pixels[offset + col + 1] else "0"
                    for col in range(8))
    return f"{int(''.join(bits), 2):016x}"


def _finding(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def evaluate(graph_path: str | Path, workspace: str | Path | None = None) -> dict[str, Any]:
    path = Path(graph_path).resolve()
    root = Path(workspace).resolve() if workspace else Path.cwd().resolve()
    findings: list[dict[str, Any]] = []
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "graph": str(path), "score": 0, "status": "error", "summary": {},
            "findings": [_finding("ERROR", "invalid_json", str(exc))],
        }

    lint_result = lint(str(path))
    for item in lint_result["findings"]:
        findings.append(_finding(item["sev"], f"lint_{item['code']}", item["msg"],
                                 node=item.get("node")))

    nodes = _nodes(graph)
    edges = graph.get("edges") or graph.get("links") or []
    by_id = {_sid(node): node for node in nodes}
    navigation = [
        element for node in nodes for element in (node.get("elements") or [])
        if (element.get("category") or "").lower() == "navigation"
        and not element.get("back")
    ]
    visited = [element for element in navigation if element.get("visited")]
    if not nodes:
        findings.append(_finding("ERROR", "no_nodes", "graph has no visual nodes"))
    if not edges and len(nodes) > 1:
        findings.append(_finding("ERROR", "missing_edges", "multiple nodes have no transitions"))

    screenshot_hashes: dict[str, list[str]] = defaultdict(list)
    screenshots: list[dict[str, Any]] = []
    for node in nodes:
        state_id = _sid(node)
        screenshot = _find_screenshot(node.get("screenshot_path"), path, root)
        if screenshot is None:
            findings.append(_finding("WARN", "missing_screenshot",
                                     "node has no readable screenshot evidence", node=state_id,
                                     screenshot_path=node.get("screenshot_path")))
            continue
        try:
            with Image.open(screenshot) as image:
                width, height = image.size
            digest = _dhash(screenshot)
            screenshot_hashes[digest].append(state_id)
            screenshots.append({"node": state_id, "page_name": node.get("page_name", ""),
                                "path": str(screenshot), "width": width, "height": height,
                                "dhash": digest})
            if width < 320 or height < 240:
                findings.append(_finding("WARN", "small_screenshot",
                                         f"{width}x{height} screenshot is weak visual evidence",
                                         node=state_id, screenshot=str(screenshot)))
        except Exception as exc:
            findings.append(_finding("ERROR", "unreadable_screenshot", str(exc),
                                     node=state_id, screenshot=str(screenshot)))

        text = " ".join([
            str(node.get("page_name") or ""),
            *(str(element.get("name") or "") for element in node.get("elements") or []),
        ]).lower()
        matched = [term for term in SUSPICIOUS_TERMS if term in text]
        if matched:
            findings.append(_finding("WARN", "suspicious_screen_text",
                                     f"possible desktop/system/error surface: {', '.join(matched)}",
                                     node=state_id, screenshot=str(screenshot)))

    for digest, state_ids in screenshot_hashes.items():
        if len(state_ids) > 1:
            findings.append(_finding("WARN", "duplicate_visual_evidence",
                                     f"identical visual hash shared by {len(state_ids)} nodes",
                                     nodes=state_ids, dhash=digest))

    for index, edge in enumerate(edges):
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        target_node = by_id.get(target)
        expected = _normalize(edge.get("target_page_name"))
        actual = _normalize((target_node or {}).get("page_name"))
        if edge.get("landing_verified") is True and expected and actual and expected != actual:
            findings.append(_finding("WARN", "landing_page_name_mismatch",
                                     "verified edge target_page_name differs from target node page_name",
                                     edge=index, source=source, target=target,
                                     expected=edge.get("target_page_name"),
                                     actual=(target_node or {}).get("page_name")))
        if target and target not in by_id:
            findings.append(_finding("ERROR", "edge_target_missing",
                                     "edge references a node absent from graph", edge=index,
                                     source=source, target=target))

    abnormal = graph.get("abnormal_buttons") or []
    for button in abnormal:
        findings.append(_finding("WARN", "abnormal_button",
                                 f"{button.get('element_name')}: {button.get('reason')}",
                                 node=button.get("state_id"), detail=button.get("detail")))

    severity = Counter(item["severity"] for item in findings)
    coverage = len(visited) / len(navigation) if navigation else None
    score = max(0, 100 - 30 * severity["ERROR"] - 7 * severity["WARN"])
    status = "error" if severity["ERROR"] else "warn" if severity["WARN"] else "pass"
    return {
        "graph": str(path), "status": status, "score": score,
        "summary": {
            "nodes": len(nodes), "edges": len(edges),
            "stop_reason": graph.get("stop_reason"),
            "navigation_elements": len(navigation), "visited_navigation": len(visited),
            "navigation_coverage": round(coverage, 4) if coverage is not None else None,
            "screenshots": len(screenshots), "abnormal_buttons": len(abnormal),
            "errors": severity["ERROR"], "warnings": severity["WARN"],
        },
        "screenshots": screenshots, "findings": findings,
    }


def _write_html(report: dict[str, Any], destination: Path) -> None:
    rows: list[str] = []
    for item in report.get("screenshots", []):
        src = Path(item["path"]).as_uri()
        rows.append(
            f"<figure><img src='{html.escape(src)}'><figcaption>"
            f"{html.escape(item['node'][:12])} — {html.escape(str(item['page_name']))}"
            "</figcaption></figure>"
        )
    findings = "\n".join(
        f"<li><b>{html.escape(item['severity'])} {html.escape(item['code'])}</b>: "
        f"{html.escape(item['message'])}</li>" for item in report["findings"]
    ) or "<li>No findings</li>"
    destination.write_text(
        "<!doctype html><meta charset='utf-8'><title>Graph quality report</title>"
        "<style>body{font-family:system-ui;margin:2rem}figure{display:inline-block;"
        "width:300px;vertical-align:top;margin:8px}img{max-width:100%;border:1px solid #bbb}"
        "figcaption{font-size:12px;word-break:break-all}</style>"
        f"<h1>Graph quality: {html.escape(report['status'])} / {report['score']}</h1>"
        f"<pre>{html.escape(json.dumps(report['summary'], ensure_ascii=False, indent=2))}</pre>"
        f"<h2>Findings</h2><ul>{findings}</ul><h2>Screenshot evidence</h2>{''.join(rows)}",
        encoding="utf-8",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--html-out", type=Path)
    parser.add_argument("--fail-on", choices=("none", "error", "warning"), default="none")
    args = parser.parse_args(argv)
    report = evaluate(args.graph, args.workspace)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    if args.html_out:
        _write_html(report, args.html_out)
    if args.fail_on == "error" and report["summary"].get("errors", 1):
        return 1
    if args.fail_on == "warning" and report["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
