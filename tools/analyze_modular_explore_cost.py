"""Offline cost and coverage audit for one or more modular explore runs."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCHEMA = "modular_explore_cost_audit.v1"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_run_dir(path: Path) -> Path:
    path = path.resolve()
    if path.is_file():
        path = path.parent
    if (path / "exploration_ledger.json").is_file():
        return path
    matches = sorted(path.glob("results/*/*/exploration_ledger.json"))
    if len(matches) == 1:
        return matches[0].parent
    if not matches:
        raise ValueError(f"no exploration_ledger.json found under {path}")
    raise ValueError(
        f"multiple modular runs found under {path}; pass one output directory"
    )


def _counter(items: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(items).items()))


def _operation_scope(operation: dict[str, Any]) -> str:
    scope = str(operation.get("scope") or "").strip()
    if scope:
        return scope
    if operation.get("element_id"):
        return "element"
    return "legacy_unspecified"


def _duplicate_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for attempt in attempts:
        action = attempt.get("action") or {}
        signature = (
            str(attempt.get("task_id") or ""),
            str(attempt.get("purpose") or action.get("purpose") or ""),
            str(action.get("kind") or ""),
            str(action.get("target") or ""),
            str(action.get("direction") or ""),
            str(action.get("operation_ref") or ""),
        )
        groups[signature].append(str(attempt.get("attempt_id") or ""))
    repeated = []
    duplicate_count = 0
    for signature, attempt_ids in groups.items():
        if len(attempt_ids) < 2:
            continue
        duplicate_count += len(attempt_ids) - 1
        repeated.append({
            "task_id": signature[0],
            "purpose": signature[1],
            "kind": signature[2],
            "target": signature[3],
            "direction": signature[4],
            "operation_ref": signature[5],
            "attempt_ids": attempt_ids,
        })
    return {
        "extra_attempts": duplicate_count,
        "groups": repeated,
    }


def _debug_metrics(path: Path) -> dict[str, Any]:
    roles: dict[str, dict[str, Any]] = {}
    totals = Counter()
    if not path.is_file():
        return {"available": False, "roles": {}, "totals": {}}

    for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
        role = str(record.get("role") or "unknown")
        metric = roles.setdefault(role, {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "transport_attempts": 0,
            "cached_tokens": 0,
            "system_prompt_chars": 0,
            "user_prompt_chars": 0,
            "max_prompt_tokens": 0,
            "format_correction_calls": 0,
            "runtime_contract_correction_calls": 0,
        })
        prompt_tokens = int(record.get("prompt_tokens") or 0)
        completion_tokens = int(record.get("completion_tokens") or 0)
        transport_attempts = int(record.get("transport_attempts") or 0)
        cached_tokens = int(
            (record.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        )
        user_prompt = str(record.get("user_prompt") or "")
        metric["calls"] += 1
        metric["prompt_tokens"] += prompt_tokens
        metric["completion_tokens"] += completion_tokens
        metric["transport_attempts"] += transport_attempts
        metric["cached_tokens"] += cached_tokens
        metric["system_prompt_chars"] += len(str(record.get("system_prompt") or ""))
        metric["user_prompt_chars"] += len(user_prompt)
        metric["max_prompt_tokens"] = max(metric["max_prompt_tokens"], prompt_tokens)
        metric["format_correction_calls"] += int("上轮格式或合同错误" in user_prompt)
        metric["runtime_contract_correction_calls"] += int(
            "上一回复未通过运行时合同" in user_prompt
        )
        totals.update({
            "calls": 1,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "transport_attempts": transport_attempts,
            "cached_tokens": cached_tokens,
        })

    for metric in roles.values():
        calls = metric["calls"]
        metric["total_tokens"] = (
            metric["prompt_tokens"] + metric["completion_tokens"]
        )
        metric["avg_prompt_tokens"] = round(metric["prompt_tokens"] / calls, 2)
        metric["avg_system_prompt_chars"] = round(
            metric["system_prompt_chars"] / calls, 2
        )
        metric["avg_user_prompt_chars"] = round(
            metric["user_prompt_chars"] / calls, 2
        )
    totals["total_tokens"] = totals["prompt_tokens"] + totals["completion_tokens"]
    return {
        "available": True,
        "roles": dict(sorted(roles.items())),
        "totals": dict(totals),
    }


def analyze_run(path: str | Path) -> dict[str, Any]:
    run_dir = _resolve_run_dir(Path(path))
    ledger = _load_json(run_dir / "exploration_ledger.json")
    completion_path = run_dir / "modular_completion.json"
    completion = _load_json(completion_path) if completion_path.is_file() else {}

    operations = ledger.get("operations") or []
    attempts = ledger.get("attempts") or []
    events = ledger.get("events") or []
    statuses_by_scope: dict[str, Counter[str]] = defaultdict(Counter)
    for operation in operations:
        statuses_by_scope[_operation_scope(operation)][
            str(operation.get("status") or "unknown")
        ] += 1

    model = _debug_metrics(run_dir / "_modular_debug.jsonl")
    actions = len(attempts)
    if model["available"]:
        totals = model["totals"]
        totals["calls_per_action"] = round(totals["calls"] / actions, 3) if actions else None
        totals["prompt_tokens_per_action"] = (
            round(totals["prompt_tokens"] / actions, 2) if actions else None
        )
        totals["total_tokens_per_action"] = (
            round(totals["total_tokens"] / actions, 2) if actions else None
        )

    return {
        "schema": SCHEMA,
        "run_dir": str(run_dir),
        "completion": {
            key: completion.get(key)
            for key in (
                "status", "stop_reason", "actions_used", "model_turns", "pages",
                "states", "regions", "elements", "operations",
                "operation_bindings", "transitions", "gaps", "bundle_status",
                "bundle_error",
            )
            if key in completion
        },
        "ledger": {
            "schema": ledger.get("schema"),
            "counts": {
                key: len(ledger.get(key) or [])
                for key in (
                    "pages", "states", "regions", "elements", "occurrences",
                    "operations", "operation_bindings", "tasks", "attempts",
                    "transitions", "events",
                )
                if key in ledger
            },
            "operation_statuses_by_scope": {
                scope: dict(sorted(counter.items()))
                for scope, counter in sorted(statuses_by_scope.items())
            },
            "attempt_outcomes": _counter([
                str(attempt.get("outcome") or "unknown") for attempt in attempts
            ]),
            "attempt_purposes": _counter([
                str(attempt.get("purpose")
                    or (attempt.get("action") or {}).get("purpose") or "unknown")
                for attempt in attempts
            ]),
            "duplicate_attempts": _duplicate_attempts(attempts),
            "event_counts": _counter([
                str(event.get("kind") or "unknown") for event in events
            ]),
        },
        "model": model,
    }


def _number(report: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = report
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "model_calls": ("model", "totals", "calls"),
        "prompt_tokens": ("model", "totals", "prompt_tokens"),
        "completion_tokens": ("model", "totals", "completion_tokens"),
        "total_tokens": ("model", "totals", "total_tokens"),
        "calls_per_action": ("model", "totals", "calls_per_action"),
        "prompt_tokens_per_action": ("model", "totals", "prompt_tokens_per_action"),
        "actions": ("ledger", "counts", "attempts"),
        "pages": ("ledger", "counts", "pages"),
        "states": ("ledger", "counts", "states"),
        "regions": ("ledger", "counts", "regions"),
        "elements": ("ledger", "counts", "elements"),
        "operations": ("ledger", "counts", "operations"),
        "transitions": ("ledger", "counts", "transitions"),
    }
    metrics = {}
    for name, path in fields.items():
        before = _number(baseline, path)
        after = _number(candidate, path)
        if before is None or after is None:
            continue
        metrics[name] = {
            "baseline": before,
            "candidate": after,
            "delta": round(after - before, 3),
            "delta_percent": round((after - before) / before * 100, 2)
            if before else None,
        }
    return {
        "baseline": baseline["run_dir"],
        "candidate": candidate["run_dir"],
        "metrics": metrics,
        "completion": {
            "baseline_status": baseline["completion"].get("status"),
            "candidate_status": candidate["completion"].get("status"),
            "baseline_gaps": baseline["completion"].get("gaps"),
            "candidate_gaps": candidate["completion"].get("gaps"),
            "baseline_bundle_status": baseline["completion"].get("bundle_status"),
            "candidate_bundle_status": candidate["completion"].get("bundle_status"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", help="modular run output directories")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args(argv)
    try:
        runs = [analyze_run(path) for path in args.runs]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    report: dict[str, Any] = {"schema": SCHEMA, "runs": runs}
    if len(runs) == 2:
        report["comparison"] = compare_runs(runs[0], runs[1])
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
