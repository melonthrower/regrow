"""Run a small Mingle traversal that exercises prompt-local ID mapping.

The default uses live VLM inventory. A fixture-inventory mode is available to
isolate later stages. Fixture grounding always stays disabled.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
LOCAL_CHOICE_RE = re.compile(r"^[cv]\d+$")
IDENTITY_KEYS = {
    "id",
    "source",
    "target",
    "element_id",
    "region_id",
    "page_id",
    "variant_id",
    "state_id",
    "action_edge_id",
    "attempt_id",
    "event_id",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a bounded Local HTML traversal with oracle inventory but real "
            "Explorer, target grounding, pixel click, and Landing."
        )
    )
    parser.add_argument("--max-actions", type=int, default=4)
    parser.add_argument("--max-states", type=int, default=4)
    parser.add_argument("--model-version", default="qwen3.7-plus")
    parser.add_argument("--result-dir", type=Path, default=None)
    parser.add_argument(
        "--inventory-source",
        choices=["vlm", "fixture"],
        default="vlm",
        help="Use live VLM inventory or the deterministic fixture inventory.",
    )
    parser.add_argument(
        "--return-policy",
        choices=["eager", "lazy"],
        default="eager",
        help="Eagerly probe return paths on arrival, or leave them for Router demand.",
    )
    parser.add_argument(
        "--forced-target",
        action="append",
        default=[],
        help="Probe-only target label; repeat to hold an A/B action path constant.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the traversal command only."
    )
    return parser.parse_args()


def default_result_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT / "artifacts" / "diagnostics" / f"mingle_mapping_probe_{stamp}"


def build_command(
    *,
    result_dir: Path,
    max_actions: int = 4,
    max_states: int = 4,
    model_version: str = "qwen3.7-plus",
    inventory_source: str = "vlm",
    return_policy: str = "eager",
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "mingle_mapping_probe_entry.py"),
        "--vm_provider",
        "local_html",
        "--html_path",
        str(ROOT / "synthetic_mobile_app" / "index.html"),
        "--screen_width",
        "412",
        "--screen_height",
        "915",
        "--headless",
        "--app_name",
        "mingle",
        "--clean_start",
        "--no_live_monitor",
        "--semantic_inventory",
        "--fixture_oracle_inventory",
        "on" if inventory_source == "fixture" else "off",
        "--fixture_oracle_grounding",
        "off",
        "--model",
        "Qwen",
        "--model_version",
        model_version,
        "--max_tokens",
        "1500",
        "--temperature",
        "0.1",
        "--max_states",
        str(max_states),
        "--max_actions",
        str(max_actions),
        "--result_dir",
        str(result_dir),
    ]
    if return_policy == "lazy":
        command.append("--no_return_path_verify")
    return command


def find_latest(root: Path, name: str) -> Path | None:
    matches = list(root.rglob(name)) if root.exists() else []
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, dict) else {}


def iter_attempts(graph: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for edge in graph.get("action_edges") or []:
        if not isinstance(edge, Mapping):
            continue
        for attempt in edge.get("attempts") or []:
            if isinstance(attempt, Mapping):
                yield attempt


def find_prompt_local_identity_refs(value: Any) -> list[dict[str, str]]:
    """Find cN/vN values only where the graph claims persistent identity."""
    findings: list[dict[str, str]] = []

    def visit(item: Any, path: str, identity_context: bool = False) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key)
                is_identity = key in IDENTITY_KEYS or key.endswith("_id")
                visit(child, f"{path}.{key}" if path else key, is_identity)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]", identity_context)
        elif identity_context and isinstance(item, str) and LOCAL_CHOICE_RE.fullmatch(item):
            findings.append({"path": path, "value": item})

    visit(value, "")
    return findings


def role_calls(ledger: Mapping[str, Any], role: str) -> int:
    roles = ledger.get("roles")
    if not isinstance(roles, Mapping):
        return 0
    record = roles.get(role)
    if not isinstance(record, Mapping):
        return 0
    try:
        return int(record.get("calls") or 0)
    except (TypeError, ValueError):
        return 0


def count_reviewed_groundings(output_root: Path | None) -> int:
    if output_root is None:
        return 0
    count = 0
    for path in output_root.glob("target_grounding_attempts/*/result.json"):
        result = load_json(path)
        reviewer = result.get("reviewer")
        if (
            isinstance(reviewer, Mapping)
            and reviewer.get("accepted") is True
            and reviewer.get("status") == "target_review_accepted"
        ):
            count += 1
    return count


def summarize(
    graph: Mapping[str, Any],
    ledger: Mapping[str, Any],
    *,
    traversal_return_code: int,
    graph_path: Path | None,
    fixture_oracle_inventory: bool = False,
    oracle_report: Mapping[str, Any] | None = None,
    oracle_validator_return_code: int | None = None,
    traversal_wall_seconds: float | None = None,
    return_policy: str = "eager",
    reviewed_groundings: int = 0,
    forced_targets: Sequence[str] = (),
) -> dict[str, Any]:
    attempts = list(iter_attempts(graph))
    verified = [
        attempt
        for attempt in attempts
        if attempt.get("committed") is True
        and attempt.get("landing_verified") is True
        and str(attempt.get("element_id") or "").strip()
    ]
    local_refs = find_prompt_local_identity_refs(graph)
    calls = {
        "explorer": role_calls(ledger, "explorer"),
        "target_grounding": role_calls(ledger, "target_grounding"),
        "target_review": role_calls(ledger, "target_review"),
    }
    checks = {
        "traversal_returned_zero": traversal_return_code == 0,
        "graph_was_written": graph_path is not None,
        "explorer_called": calls["explorer"] > 0,
        "real_target_grounding_called": calls["target_grounding"] > 0,
        "target_reviewer_called": calls["target_review"] > 0,
        "reviewer_accepted_grounding_recorded": reviewed_groundings > 0,
        "verified_landing_recorded": bool(verified),
        "no_prompt_local_identity_persisted": not local_refs,
    }
    return {
        "schema_version": "rewalk.mingle_mapping_probe.v2",
        "status": "pass" if all(checks.values()) else "fail",
        "scope": {
            "environment": "local_html",
            "fixture_oracle_inventory": fixture_oracle_inventory,
            "fixture_oracle_grounding": False,
            "return_policy": return_policy,
            "forced_targets": list(forced_targets),
            "real_vlm_roles": [
                "explorer", "target_grounding", "target_review"],
            "claim_limit": "Not Android/device evidence and not a coverage certificate.",
        },
        "traversal_return_code": traversal_return_code,
        "traversal_wall_seconds": traversal_wall_seconds,
        "graph_path": str(graph_path) if graph_path else "",
        "counts": {
            "nodes": len(graph.get("nodes") or []),
            "action_edges": len(graph.get("action_edges") or []),
            "attempts": len(attempts),
            "verified_landing_attempts": len(verified),
            "reviewed_groundings": reviewed_groundings,
        },
        "vlm_calls": {
            "roles": calls,
            "logical_calls": int(ledger.get("logical_calls") or 0),
            "transport_attempts": int(ledger.get("transport_attempts") or 0),
            "cache_hits": int(ledger.get("cache_hits") or 0),
            "latency_seconds": float(ledger.get("latency_seconds") or 0.0),
            "prompt_tokens": int(ledger.get("prompt_tokens") or 0),
            "completion_tokens": int(ledger.get("completion_tokens") or 0),
        },
        "verified_actions": [
            {
                "element_id": str(attempt.get("element_id") or ""),
                "element_label": str(attempt.get("element_label") or ""),
                "source": str(attempt.get("source") or ""),
                "target": str(attempt.get("target") or ""),
                "outcome": str(attempt.get("outcome") or ""),
            }
            for attempt in verified
        ],
        "prompt_local_identity_refs": local_refs,
        "checks": checks,
        "oracle_completeness": {
            "validator_return_code": oracle_validator_return_code,
            "status": (oracle_report or {}).get("status", "not_run"),
            "required_for_probe_pass": False,
        },
    }


def run_oracle_validator(graph_path: Path) -> tuple[int, dict[str, Any], Path]:
    report_path = graph_path.parent / "oracle_validation.json"
    command = [
        sys.executable,
        str(ROOT / "synthetic_mobile_app" / "validate_graph.py"),
        str(graph_path),
        "--json-out",
        str(report_path),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (graph_path.parent / "oracle_validation.log").write_text(
        result.stdout or "", encoding="utf-8"
    )
    return result.returncode, load_json(report_path), report_path


def main() -> int:
    args = parse_args()
    if args.max_actions < 1 or args.max_states < 1:
        raise SystemExit("--max-actions and --max-states must be positive")

    result_dir = (args.result_dir or default_result_dir()).resolve()
    command = build_command(
        result_dir=result_dir,
        max_actions=args.max_actions,
        max_states=args.max_states,
        model_version=args.model_version,
        inventory_source=args.inventory_source,
        return_policy=args.return_policy,
    )
    if args.dry_run:
        print(json.dumps(command, ensure_ascii=False, indent=2))
        return 0

    result_dir.mkdir(parents=True, exist_ok=True)
    print("Running isolated Mingle mapping traversal...")
    started = time.perf_counter()
    child_env = dict(os.environ)
    child_env["GUIWALK_PROBE_FORCED_TARGETS"] = json.dumps(
        list(args.forced_target), ensure_ascii=False
    )
    traversal = subprocess.run(command, cwd=ROOT, check=False, env=child_env)
    traversal_wall_seconds = round(time.perf_counter() - started, 3)

    graph_path = find_latest(result_dir, "graph.json")
    graph = load_json(graph_path)
    ledger_path = graph_path.parent / "vlm_calls.json" if graph_path else None
    ledger = load_json(ledger_path)
    validator_code: int | None = None
    oracle_report: dict[str, Any] = {}
    oracle_report_path: Path | None = None
    if graph_path:
        validator_code, oracle_report, oracle_report_path = run_oracle_validator(
            graph_path
        )
    reviewed_groundings = count_reviewed_groundings(
        graph_path.parent if graph_path else None
    )

    summary = summarize(
        graph,
        ledger,
        traversal_return_code=traversal.returncode,
        graph_path=graph_path,
        fixture_oracle_inventory=args.inventory_source == "fixture",
        oracle_report=oracle_report,
        oracle_validator_return_code=validator_code,
        traversal_wall_seconds=traversal_wall_seconds,
        return_policy=args.return_policy,
        reviewed_groundings=reviewed_groundings,
        forced_targets=args.forced_target,
    )
    summary["vlm_ledger_path"] = str(ledger_path) if ledger_path else ""
    summary["oracle_report_path"] = (
        str(oracle_report_path) if oracle_report_path else ""
    )
    summary_path = (
        graph_path.parent / "mapping_probe_summary.json"
        if graph_path
        else result_dir / "mapping_probe_summary.json"
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Probe summary -> {summary_path}")
    return 0 if summary["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
