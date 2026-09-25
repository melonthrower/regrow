"""Scan top-level defs / classes in gui_rewalk and flag ones whose name
appears ONLY at the definition site (never called anywhere, inside or
outside the defining file).

Heuristic only — caveats:
  - misses string-based dispatch (getattr / eval / cmd registries)
  - method names on classes are not analysed
  - dunder names are always treated as used

Search scope:
  - DEFINITIONS are collected only from gui_rewalk/ (excluding gui_rewalk/tools).
  - USAGES are scanned across both gui_rewalk/ AND its sibling external
    callers in mywork/ — tools/, test_*.py, top-level scripts, even
    driver shells (*.ps1, *.sh). External callers were the gap that hid
    real consumers like mywork/tools/run_omniparser_poc.py.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # gui_rewalk/
MYWORK = ROOT.parent                                   # mywork/

# Directories to skip when walking mywork/ for usage scans — third-party trees
# and result/log dirs that would produce false-positive name matches without
# being actual callers.
SKIP_DIRS_IN_MYWORK = {
    "OSWorld", "OmniParser", ".claude", ".git", ".vscode",
    "node_modules", "__pycache__", "logs", "design", "research",
    "patches", "evaluation_examples", "llm_cost", "figs",
}
# Anything starting with these prefixes inside mywork is generated output.
SKIP_PREFIXES_IN_MYWORK = ("result_", "result", "clock_issue_visualization",
                           "vibecoding")

DEF_DIRS_EXCLUDE = {"__pycache__", "tools"}            # exclude when collecting DEFS
USAGE_DIRS_EXCLUDE_IN_GUIREWALK = {"__pycache__"}      # gui_rewalk usage scope
USAGE_FILE_GLOBS = ("*.py", "*.ps1", "*.sh")           # include driver shells


def iter_def_files():
    """Files where we collect top-level definitions (gui_rewalk source)."""
    seen = set()
    for p in ROOT.rglob("*.py"):
        if any(part in DEF_DIRS_EXCLUDE for part in p.parts):
            continue
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        yield p


def _is_skipped_in_mywork(p: Path) -> bool:
    try:
        rel = p.relative_to(MYWORK)
    except ValueError:
        return False
    parts = rel.parts
    if not parts:
        return False
    head = parts[0]
    if head in SKIP_DIRS_IN_MYWORK:
        return True
    if any(head.startswith(pref) for pref in SKIP_PREFIXES_IN_MYWORK):
        return True
    if any(part == "__pycache__" for part in parts):
        return True
    return False


def iter_use_files():
    """Files scanned for usage counts: gui_rewalk + mywork outer scripts."""
    seen = set()
    # gui_rewalk itself
    for p in ROOT.rglob("*.py"):
        if any(part in USAGE_DIRS_EXCLUDE_IN_GUIREWALK for part in p.parts):
            continue
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        yield p
    # mywork/ outer (excluding gui_rewalk subtree which we already covered)
    for glob in USAGE_FILE_GLOBS:
        for p in MYWORK.rglob(glob):
            if ROOT in p.parents or p == ROOT:
                continue
            if _is_skipped_in_mywork(p):
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            yield p


def collect_top_level_defs(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "func"
        elif isinstance(node, ast.ClassDef):
            kind = "class"
        else:
            continue
        if node.name.startswith("__") and node.name.endswith("__"):
            continue
        out.append((node.name, node.lineno, kind))
    return out


def_files = list(iter_def_files())
use_files = list(iter_use_files())

# Collect all defs first (from gui_rewalk only).
all_defs: list[tuple[str, Path, int, str]] = []
for f in def_files:
    for name, lineno, kind in collect_top_level_defs(f):
        all_defs.append((name, f, lineno, kind))

# Count word-boundary occurrences across the FULL usage scope (gui_rewalk +
# mywork external callers). A def is dead iff occurrences == number-of-defs
# (the definition line itself is the only occurrence).
names = sorted({d[0] for d in all_defs})
pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
counts: dict[str, int] = defaultdict(int)
for f in use_files:
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    for m in pattern.finditer(text):
        counts[m.group(1)] += 1

def_count: dict[str, int] = defaultdict(int)
for name, _, _, _ in all_defs:
    def_count[name] += 1

orphans_by_file: dict[Path, list[tuple[str, int, str]]] = defaultdict(list)
for name, path, lineno, kind in all_defs:
    if counts.get(name, 0) <= def_count[name]:
        orphans_by_file[path].append((name, lineno, kind))

print(f"# Def files (gui_rewalk):  {len(def_files)}")
print(f"# Usage files (gui_rewalk + mywork outer): {len(use_files)}")
print(f"# Top-level defs in gui_rewalk: {len(all_defs)}")
total_orphan = sum(len(v) for v in orphans_by_file.values())
print(f"# Orphans: {total_orphan} across {len(orphans_by_file)} files\n")

for f in sorted(orphans_by_file.keys()):
    rel = f.relative_to(ROOT)
    print(f"\n== {rel} ==")
    for name, lineno, kind in sorted(orphans_by_file[f], key=lambda x: x[1]):
        print(f"  L{lineno:>5}  {kind:5}  {name}")
