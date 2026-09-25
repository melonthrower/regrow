from __future__ import annotations

import json
from pathlib import Path

from tools.analyze_modular_explore_cost import analyze_run, compare_runs, main


def _write_run(root: Path, *, prompt_tokens: int = 100) -> Path:
    run_dir = root / "results" / "20260823" / "clock"
    run_dir.mkdir(parents=True)
    (run_dir / "exploration_ledger.json").write_text(json.dumps({
        "schema": "exploration_ledger.v3",
        "pages": [{"page_id": "p1"}],
        "states": [{"state_id": "s1"}],
        "regions": [{"region_id": "r1"}],
        "elements": [{"element_id": "el1"}],
        "occurrences": [],
        "operations": [
            {"operation_id": "o1", "scope": "element", "element_id": "el1",
             "status": "verified"},
            {"operation_id": "o2", "scope": "region", "direction": "left",
             "status": "recorded"},
        ],
        "operation_bindings": [],
        "tasks": [],
        "attempts": [
            {"attempt_id": "a1", "task_id": "t1", "purpose": "execute",
             "outcome": "success", "action": {"kind": "click", "target": "Start",
             "operation_ref": "o1", "direction": ""}},
            {"attempt_id": "a2", "task_id": "t1", "purpose": "execute",
             "outcome": "no_effect", "action": {"kind": "click", "target": "Start",
             "operation_ref": "o1", "direction": ""}},
        ],
        "transitions": [{"transition_id": "e1"}],
        "events": [{"kind": "action_executed"}, {"kind": "action_executed"}],
    }), encoding="utf-8")
    (run_dir / "modular_completion.json").write_text(json.dumps({
        "status": "complete", "gaps": [], "bundle_status": "compiled",
    }), encoding="utf-8")
    (run_dir / "_modular_debug.jsonl").write_text(json.dumps({
        "role": "modular_main_agent",
        "system_prompt": "system",
        "user_prompt": "上轮格式或合同错误",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": 20,
        "transport_attempts": 1,
        "prompt_tokens_details": {"cached_tokens": 25},
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    return run_dir


def test_analyze_run_reports_cost_coverage_and_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    run_dir = _write_run(root)

    report = analyze_run(root)

    assert report["run_dir"] == str(run_dir.resolve())
    assert report["ledger"]["operation_statuses_by_scope"] == {
        "element": {"verified": 1},
        "region": {"recorded": 1},
    }
    assert report["ledger"]["duplicate_attempts"]["extra_attempts"] == 1
    assert report["ledger"]["event_counts"] == {"action_executed": 2}
    totals = report["model"]["totals"]
    assert totals["calls"] == 1
    assert totals["prompt_tokens_per_action"] == 50.0
    role = report["model"]["roles"]["modular_main_agent"]
    assert role["cached_tokens"] == 25
    assert role["format_correction_calls"] == 1


def test_compare_runs_calculates_cost_delta(tmp_path: Path) -> None:
    baseline = analyze_run(_write_run(tmp_path / "baseline", prompt_tokens=100))
    candidate = analyze_run(_write_run(tmp_path / "candidate", prompt_tokens=75))

    comparison = compare_runs(baseline, candidate)

    assert comparison["metrics"]["prompt_tokens"] == {
        "baseline": 100.0,
        "candidate": 75.0,
        "delta": -25.0,
        "delta_percent": -25.0,
    }
    assert comparison["completion"]["candidate_status"] == "complete"


def test_main_writes_two_run_report(tmp_path: Path) -> None:
    baseline = _write_run(tmp_path / "baseline", prompt_tokens=100)
    candidate = _write_run(tmp_path / "candidate", prompt_tokens=75)
    output = tmp_path / "reports" / "audit.json"

    assert main([str(baseline), str(candidate), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "modular_explore_cost_audit.v1"
    assert report["comparison"]["metrics"]["prompt_tokens"]["delta_percent"] == -25.0
