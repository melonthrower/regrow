"""Compare a GUI-ReWalk schema-v3 graph with the synthetic app oracle.

The comparison is intentionally semantic: runtime Page/Variant IDs are opaque,
so observed Pages are aligned to canonical fixture Pages through unique visible
anchors.  The report then checks Page splits/merges, control inventory, verified
direct transitions, overlay attachment, and long-scroll ledger evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent


def _norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return data


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    rows = graph.get("nodes") or []
    if isinstance(rows, dict):
        return [dict(value, state_id=key) for key, value in rows.items()]
    return [row for row in rows if isinstance(row, dict)]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("state_id") or node.get("id") or "")


def _node_text(node: dict[str, Any]) -> str:
    values: list[str] = [
        str(node.get("page_name") or ""),
        str(node.get("semantic_page_key") or ""),
    ]
    for element in node.get("elements") or []:
        if not isinstance(element, dict):
            continue
        values.extend(
            str(element.get(key) or "")
            for key in ("name", "description", "semantic_description")
        )
    return _norm(" ".join(values))


def _node_labels(node: dict[str, Any]) -> set[str]:
    labels = {
        _norm(node.get("page_name")),
        _norm(node.get("semantic_page_key")),
    }
    for element in node.get("elements") or []:
        if not isinstance(element, dict):
            continue
        for key in ("name", "description", "semantic_description"):
            labels.add(_norm(element.get(key)))
    labels.discard("")
    return labels


def _has_phrase(text: str, phrase: str) -> bool:
    needle = _norm(phrase)
    return bool(needle) and needle in text


def _verified_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    verified = []
    for edge in graph.get("action_edges") or []:
        if not isinstance(edge, dict):
            continue
        attempts = [row for row in edge.get("attempts") or [] if isinstance(row, dict)]
        success = bool(edge.get("routing_verified")) and any(
            row.get("committed") is True and row.get("landing_verified") is True
            for row in attempts
        )
        if success:
            verified.append(edge)
    return verified


def _edge_label(edge: dict[str, Any]) -> str:
    selector = (edge.get("action") or {}).get("selector") or {}
    return str(
        selector.get("element_label")
        or selector.get("description")
        or edge.get("element_label")
        or edge.get("semantic_description")
        or ""
    )


def _label_matches(transition: dict[str, Any], label: str) -> bool:
    normalized = _norm(label)
    exact = transition.get("action_label")
    if exact is not None:
        return normalized == _norm(exact)
    aliases = transition.get("action_labels") or []
    if aliases:
        return normalized in {_norm(value) for value in aliases}
    prefix = transition.get("action_label_pattern")
    return bool(prefix) and normalized.startswith(_norm(prefix))


def _is_semantic_back(transition: dict[str, Any], edge: dict[str, Any]) -> bool:
    """Accept a verified platform Back for an expected return/dismiss edge.

    The traversal may legitimately choose the operating-system Back action
    instead of clicking a visible back/cancel control.  Source and target Page
    checks still run below, so this does not turn an arbitrary Back into a
    matching transition.
    """
    action = edge.get("action") or {}
    return (
        str(action.get("action_type") or "").upper() == "BACK"
        and transition.get("effect") in {"return", "dismiss_overlay"}
    )


def _page_alignment(
    oracle: dict[str, Any], nodes: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, list[str]], list[dict[str, Any]]]:
    canonical = {page["id"]: page for page in oracle["pages"]}
    by_observed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        page_id = str(node.get("page_id") or "")
        if page_id:
            by_observed[page_id].append(node)

    observed_to_canonical: dict[str, str] = {}
    canonical_to_observed: dict[str, list[str]] = defaultdict(list)
    ambiguous: list[dict[str, Any]] = []
    for observed_id, members in by_observed.items():
        text = " ".join(_node_text(member) for member in members)
        labels = set().union(*(_node_labels(member) for member in members))
        scores: dict[str, int] = {}
        identity_hits: dict[str, int] = {}
        for page_id, page in canonical.items():
            scores[page_id] = sum(
                1 for anchor in page.get("anchors") or [] if _has_phrase(text, anchor)
            )
            identity_hits[page_id] = sum(
                1 for anchor in page.get("identity_anchors") or page.get("anchors", [])[:1]
                if _norm(anchor) in labels
            )
        ranked = sorted(
            scores,
            key=lambda page_id: (-identity_hits[page_id], -scores[page_id], page_id),
        )
        if not ranked or identity_hits[ranked[0]] <= 0:
            continue
        best_id = ranked[0]
        best_score = scores[best_id]
        observed_to_canonical[observed_id] = best_id
        canonical_to_observed[best_id].append(observed_id)
        positive_identity = [
            page_id for page_id, count in identity_hits.items() if count > 0
        ]
        tied = [
            page_id for page_id in positive_identity
            if identity_hits[page_id] == identity_hits[best_id]
            and scores[page_id] == best_score
        ]
        if len(tied) > 1 or len(positive_identity) > 1:
            ambiguous.append({
                "observed_page_id": observed_id,
                "selected": best_id,
                "scores": {page_id: scores[page_id] for page_id in positive_identity},
            })
    return observed_to_canonical, dict(canonical_to_observed), ambiguous


def _canonical_for_state(
    state_id: str,
    nodes_by_id: dict[str, dict[str, Any]],
    observed_to_canonical: dict[str, str],
) -> str:
    node = nodes_by_id.get(str(state_id)) or {}
    return observed_to_canonical.get(str(node.get("page_id") or ""), "")


def _transition_sources(transition: dict[str, Any]) -> list[str]:
    if transition.get("source_page"):
        return [str(transition["source_page"])]
    return [str(value) for value in transition.get("source_pages") or []]


def validate(oracle: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _nodes(graph)
    nodes_by_id = {_node_id(node): node for node in nodes}
    observed_to_canonical, canonical_to_observed, ambiguous = _page_alignment(
        oracle, nodes
    )
    findings: list[dict[str, Any]] = []

    def add(code: str, severity: str, message: str, **evidence: Any) -> None:
        findings.append({
            "code": code,
            "severity": severity,
            "message": message,
            "evidence": evidence,
        })

    expected_page_ids = [page["id"] for page in oracle["pages"]]
    for page_id in expected_page_ids:
        observed = canonical_to_observed.get(page_id, [])
        if not observed:
            add("missing_page", "ERROR", f"No observed Page aligned to {page_id}")
        elif len(observed) > 1:
            add(
                "page_split",
                "ERROR",
                f"Canonical Page {page_id} split across {len(observed)} observed Page IDs",
                observed_page_ids=observed,
            )
    for row in ambiguous:
        add(
            "possible_page_merge",
            "ERROR",
            "One observed Page contains anchors from multiple canonical Pages",
            **row,
        )

    # Inventory coverage is checked on every node aligned to the canonical Page.
    page_text: dict[str, str] = defaultdict(str)
    for node in nodes:
        canonical_id = observed_to_canonical.get(str(node.get("page_id") or ""), "")
        if canonical_id:
            page_text[canonical_id] += " " + _node_text(node)
    for page in oracle["pages"]:
        text = page_text.get(page["id"], "")
        controls = page.get("controls") or []
        group_hits: dict[str, bool] = defaultdict(bool)
        for control in controls:
            labels = [control.get("label"), control.get("alternate_label")]
            present = any(label and _has_phrase(text, str(label)) for label in labels)
            group = str(control.get("group") or "")
            if group and present:
                group_hits[group] = True
            if present or control.get("coverage") == "group_once":
                continue
            add(
                "missing_control",
                "ERROR",
                f"Control {control.get('label')} was not inventoried on {page['id']}",
                page_id=page["id"],
                control_id=control.get("id"),
            )
        for group in {str(row.get("group")) for row in controls if row.get("group")}:
            if not group_hits[group]:
                add(
                    "missing_control_group",
                    "ERROR",
                    f"No member of control group {group} was inventoried",
                    page_id=page["id"],
                )

    verified_edges = _verified_edges(graph)
    for transition in oracle.get("transitions") or []:
        if not transition.get("required", True):
            continue
        sources = _transition_sources(transition)
        coverage = transition.get("coverage") or "per_source"
        required_sources: Iterable[str | None] = [None] if coverage in {
            "shared_once", "group_once"
        } else sources
        for required_source in required_sources:
            matched = False
            for edge in verified_edges:
                source = _canonical_for_state(
                    str(edge.get("source") or ""), nodes_by_id, observed_to_canonical
                )
                target = _canonical_for_state(
                    str(edge.get("target") or ""), nodes_by_id, observed_to_canonical
                )
                if required_source is not None and source != required_source:
                    continue
                if required_source is None and source not in sources:
                    continue
                if (not _label_matches(transition, _edge_label(edge))
                        and not _is_semantic_back(transition, edge)):
                    continue
                expected_target = transition.get("target_page")
                if expected_target == "$source":
                    if target != source:
                        continue
                elif target != expected_target:
                    continue
                matched = True
                break
            if not matched:
                add(
                    "missing_verified_transition",
                    "ERROR",
                    f"Missing verified transition {transition['id']}",
                    source_page=required_source or sources,
                    action=(transition.get("action_label")
                            or transition.get("action_labels")
                            or transition.get("action_label_pattern")),
                    target_page=transition.get("target_page"),
                    coverage=coverage,
                )

    # An overlay should reuse its host's observed Page ID.  This catches the
    # common failure where a popup/dialog is registered as a new semantic Page.
    for surface in oracle.get("surfaces") or []:
        anchors = surface.get("anchors") or []
        surface_nodes = [
            node for node in nodes
            if anchors and sum(_has_phrase(_node_text(node), anchor) for anchor in anchors) >= 1
        ]
        if not surface_nodes:
            add(
                "missing_surface",
                "ERROR",
                f"Surface {surface['id']} was not observed",
                host_pages=surface.get("host_pages"),
            )
            continue
        for surface_node in surface_nodes:
            target_state = _node_id(surface_node)
            incoming = [edge for edge in verified_edges if str(edge.get("target") or "") == target_state]
            for edge in incoming:
                source_node = nodes_by_id.get(str(edge.get("source") or "")) or {}
                source_page_id = str(source_node.get("page_id") or "")
                target_page_id = str(surface_node.get("page_id") or "")
                if source_page_id and target_page_id and source_page_id != target_page_id:
                    add(
                        "overlay_detached_page",
                        "ERROR",
                        f"Surface {surface['id']} became a different observed Page",
                        source_state=edge.get("source"),
                        target_state=target_state,
                        source_page_id=source_page_id,
                        target_page_id=target_page_id,
                    )

    ledgers = [row for row in graph.get("scroll_ledger") or [] if isinstance(row, dict)]
    for page in oracle["pages"]:
        expected = page.get("scroll") or {}
        if expected.get("classification") != "scrollable":
            continue
        observed_page_ids = set(canonical_to_observed.get(page["id"], []))
        state_ids = {
            _node_id(node) for node in nodes
            if str(node.get("page_id") or "") in observed_page_ids
        }
        candidates = [
            row for row in ledgers
            if state_ids.intersection(str(value) for value in row.get("state_ids") or [])
        ]
        complete = [
            row for row in candidates
            if row.get("classification") == "scrollable"
            and row.get("bottom_reached") is True
            and row.get("top_restored") is True
            and row.get("complete") is True
            and int(row.get("steps") or 0) >= int(expected.get("min_scroll_steps") or 0)
        ]
        if not complete:
            add(
                "incomplete_scroll_scope",
                "ERROR",
                f"Long Page {page['id']} lacks complete bottom/top scroll evidence",
                observed_state_ids=sorted(state_ids),
                candidate_ledgers=candidates,
                expected=expected,
            )

    counts = {
        "canonical_pages": len(expected_page_ids),
        "observed_states": len(nodes),
        "observed_pages": len({str(node.get("page_id") or "") for node in nodes if node.get("page_id")}),
        "aligned_pages": len(canonical_to_observed),
        "verified_edges": len(verified_edges),
        "scroll_ledger_records": len(ledgers),
        "errors": sum(row["severity"] == "ERROR" for row in findings),
    }
    return {
        "schema_version": "rewalk.synthetic_app.validation.v1",
        "status": "pass" if counts["errors"] == 0 else "fail",
        "counts": counts,
        "alignment": {
            "observed_to_canonical": observed_to_canonical,
            "canonical_to_observed": canonical_to_observed,
        },
        "findings": findings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate GUI-ReWalk graph against fixture oracle")
    parser.add_argument("graph_json", type=Path)
    parser.add_argument("--oracle", type=Path, default=ROOT / "oracle.json")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate(_load(args.oracle), _load(args.graph_json))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    counts = report["counts"]
    print(
        f"fixture validation: {report['status'].upper()} | "
        f"states={counts['observed_states']} pages={counts['observed_pages']} "
        f"aligned={counts['aligned_pages']}/{counts['canonical_pages']} "
        f"verified_edges={counts['verified_edges']} errors={counts['errors']}"
    )
    for finding in report["findings"]:
        print(f"[{finding['severity']}] {finding['code']}: {finding['message']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
