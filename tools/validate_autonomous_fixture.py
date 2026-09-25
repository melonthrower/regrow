"""Post-run fixture acceptance for screenshot-only autonomous traversal."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple


def _norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _controls(oracle: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    controls: Dict[str, Dict[str, Any]] = {}
    for owner in [*(oracle.get("pages") or []), *(oracle.get("surfaces") or [])]:
        for control in owner.get("controls") or []:
            controls[str(control.get("id") or "")] = dict(control)
    return controls


def _attempts(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    grouped: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for record in trace.get("fixture_audit") or []:
        index = record.get("event_index")
        if not isinstance(index, int):
            continue
        phase = str(record.get("phase") or "")
        if phase in {"before", "after"}:
            grouped[index][phase] = record
    return [
        {"event_index": index, **grouped[index]}
        for index in sorted(grouped)
        if "before" in grouped[index] and "after" in grouped[index]
    ]


def _labels(transition: Dict[str, Any]) -> set[str]:
    values = transition.get("action_labels") or []
    if transition.get("action_label"):
        values = [transition["action_label"], *values]
    return {_norm(value) for value in values if _norm(value)}


def _matches_transition(
    transition: Dict[str, Any], attempt: Dict[str, Any],
    controls: Dict[str, Dict[str, Any]],
) -> bool:
    before, after = attempt["before"], attempt["after"]
    source = str(transition.get("source_page") or "")
    if source and str(before.get("page") or "") != source:
        return False
    source_surface = str(transition.get("source_surface") or "")
    if source_surface != str(before.get("surface") or ""):
        return False
    action_id = str(before.get("action_id") or "")
    control = controls.get(action_id) or {}
    actual_labels = {
        _norm(action_id), _norm(control.get("label")),
        _norm(control.get("alternate_label")), _norm(before.get("action_label")),
    }
    if action_id != str(transition.get("id") or "") \
            and not (_labels(transition) & actual_labels):
        return False
    target_page = str(transition.get("target_page") or "")
    if target_page == "$source":
        target_page = source
    if target_page and str(after.get("page") or "") != target_page:
        return False
    target_surface = str(transition.get("target_surface") or "")
    if target_surface and str(after.get("surface") or "") != target_surface:
        return False
    effect = str(transition.get("effect") or "")
    if effect == "dismiss_overlay" and str(after.get("surface") or ""):
        return False
    if effect == "state_change" \
            and dict(before.get("state") or {}) == dict(after.get("state") or {}):
        return False
    return True


def _transition_units(
    oracle: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    units: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for transition in oracle.get("transitions") or []:
        if transition.get("required") is not True:
            continue
        key = str(transition.get("id") or "")
        if transition.get("effect") == "peer_navigation":
            key = "primary_navigation:" + str(transition.get("target_page") or "")
        units[key].append(transition)
    return dict(units)


def _scroll_checks(
    oracle: Dict[str, Any], audit: List[Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    missing_bottom: List[str] = []
    missing_restore: List[str] = []
    for page in oracle.get("pages") or []:
        scroll = page.get("scroll") or {}
        if scroll.get("classification") != "scrollable":
            continue
        page_id = str(page.get("id") or "")
        samples = [row for row in audit if row.get("page") == page_id]
        bottom_indices = [
            index for index, row in enumerate(samples)
            if (row.get("scroll") or {}).get("bottom") is True
        ]
        if not bottom_indices:
            missing_bottom.append(page_id)
            continue
        if scroll.get("must_restore_top") is True and not any(
                index > bottom_indices[0]
                and (row.get("scroll") or {}).get("top") is True
                for index, row in enumerate(samples)):
            missing_restore.append(page_id)
    return missing_bottom, missing_restore


def _unproductive_repeats(attempts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    repeats: List[Dict[str, Any]] = []
    for attempt in attempts:
        before, after = attempt["before"], attempt["after"]
        action_id = str(before.get("action_id") or "")
        key = (str(before.get("page") or ""), action_id)
        changed = any((
            before.get("page") != after.get("page"),
            before.get("surface") != after.get("surface"),
            before.get("state") != after.get("state"),
            before.get("scroll") != after.get("scroll"),
        ))
        if action_id and key in seen and not changed:
            repeats.append({
                "event_index": attempt["event_index"],
                "page": key[0], "action_id": action_id,
            })
        seen.add(key)
    return repeats


def validate(oracle: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    audit = [row for row in trace.get("fixture_audit") or []
             if isinstance(row, dict) and not row.get("error")]
    attempts = _attempts(trace)
    controls = _controls(oracle)
    pages_seen = {str(row.get("page") or "") for row in audit}
    surfaces_seen = {str(row.get("surface") or "") for row in audit}
    pages_expected = {str(row.get("id") or "") for row in oracle.get("pages") or []}
    surfaces_expected = {
        str(row.get("id") or "") for row in oracle.get("surfaces") or []}

    units = _transition_units(oracle)
    missing_units = [
        key for key, transitions in units.items()
        if not any(_matches_transition(transition, attempt, controls)
                   for transition in transitions for attempt in attempts)
    ]
    missing_bottom, missing_restore = _scroll_checks(oracle, audit)
    initial = next((row for row in audit if row.get("phase") == "initial"), {})
    final = next((row for row in reversed(audit)
                  if row.get("phase") == "final"), {})
    state_restored = bool(initial and final) and (
        dict(initial.get("state") or {}) == dict(final.get("state") or {}))
    repeats = _unproductive_repeats(attempts)
    checks = {
        "pages": not (pages_expected - pages_seen),
        "surfaces": not (surfaces_expected - surfaces_seen),
        "distinct_transitions": not missing_units,
        "scroll_bottom": not missing_bottom,
        "scroll_restored": not missing_restore,
        "state_restored": state_restored,
        "no_unproductive_repeats": not repeats,
        "model_finished": trace.get("stop_reason") == "model_finished",
    }
    return {
        "schema": "gui_rewalk.autonomous_fixture_coverage.v1",
        "status": "certified" if all(checks.values()) else "incomplete",
        "checks": checks,
        "observed": {
            "pages": sorted(pages_seen - {""}),
            "surfaces": sorted(surfaces_seen - {""}),
            "transition_units": len(units) - len(missing_units),
            "transition_units_total": len(units),
            "actions": len(attempts),
        },
        "missing": {
            "pages": sorted(pages_expected - pages_seen),
            "surfaces": sorted(surfaces_expected - surfaces_seen),
            "transition_units": missing_units,
            "scroll_bottom": missing_bottom,
            "scroll_restore": missing_restore,
        },
        "unproductive_repeats": repeats,
        "initial_state": initial.get("state") or {},
        "final_state": final.get("state") or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("oracle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    oracle = json.loads(args.oracle.read_text(encoding="utf-8"))
    report = validate(oracle, trace)
    output = args.output or args.trace.with_name("autonomous_coverage.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "certified" else 3


if __name__ == "__main__":
    raise SystemExit(main())
