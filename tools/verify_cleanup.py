"""Offline verification harness for the dead-code cleanup (spec 2026-07-07).

Three check groups: compileall, per-module import, tests/test_* offline
tests, entry --help smokes. Results are compared against a saved baseline
so pre-existing failures are never blamed on the cleanup.

Usage:
    python tools/verify_cleanup.py --save-baseline   # once, before any deletion
    python tools/verify_cleanup.py --compare         # after each deletion batch
"""
import argparse
import compileall
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "artifacts" / "scratch" / "verify_baseline.json"
PY = sys.executable
PYTHONPATH = os.pathsep.join([str(ROOT), str(ROOT / "OSWorld")])


def _run(cmd, timeout):
    env = dict(os.environ, PYTHONPATH=PYTHONPATH)
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    if r.returncode == 0:
        return "PASS"
    tail = (r.stderr or r.stdout or "").strip().splitlines()
    return "FAIL: " + (tail[-1][:200] if tail else "rc=%d" % r.returncode)


def collect():
    results = {}
    ok = compileall.compile_dir(str(ROOT / "gui_rewalk"), quiet=2, force=True)
    ok = compileall.compile_dir(str(ROOT / "tools"), quiet=2, force=True) and ok
    ok = compileall.compile_dir(str(ROOT / "tests"), quiet=2, force=True) and ok
    results["compileall"] = "PASS" if ok else "FAIL"
    for p in sorted((ROOT / "gui_rewalk").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        mod = ".".join(p.relative_to(ROOT).with_suffix("").parts)
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        results["import:" + mod] = _run([PY, "-c", "import " + mod], 90)
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        results["test:" + p.name] = _run([PY, str(p)], 300)
    for p in sorted((ROOT / "gui_rewalk").glob("run_*.py")):
        results["help:" + p.name] = _run([PY, str(p), "--help"], 120)
    return results


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save-baseline", action="store_true")
    g.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    results = collect()
    if args.save_baseline:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(results, indent=1, ensure_ascii=False),
                            encoding="utf-8")
        bad = sorted(k for k, v in results.items() if v != "PASS")
        print("baseline saved: %d checks, %d pre-existing non-PASS"
              % (len(results), len(bad)))
        for k in bad:
            print("  [pre-existing]", k, "->", results[k])
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    new_fail = sorted(k for k, v in results.items()
                      if v != "PASS" and base.get(k) == "PASS")
    removed = sorted(k for k in base if k not in results)
    print("compare: %d checks, %d NEW failures, %d checks removed"
          % (len(results), len(new_fail), len(removed)))
    for k in new_fail:
        print("  [NEW FAIL]", k, "->", results[k])
    for k in removed:
        print("  [removed-check]", k)
    return 1 if new_fail else 0


if __name__ == "__main__":
    sys.exit(main())
