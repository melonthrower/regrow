"""D18 fix candidate validation (read-only, no production code changed).

Candidate: in the state-id skeleton, elements that live inside a *scrollable
container* (identified by container_chain) contribute a COARSE per-container
signature (container key + bucketed count) instead of enumerating each row.
Rows scrolling in/out then no longer change the hash, while container presence
and rough size still split genuinely different pages.

Validates against the real split pairs found by probe_d18_scroll_split.py.
We compare: do the two views of the SAME page now hash equal, while DIFFERENT
pages still hash differently.

Run: python tools/validate_d18_fix.py
"""
import json
import hashlib
from pathlib import Path
from itertools import combinations
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]

# Container-chain leaf tokens that indicate a scrollable list region.
SCROLL_CONTAINER_HINTS = ("recycler_view", "apps_list", "list_container",
                          "scroll", "content_frame")
_NAME_STABLE = {"list-item", "push-button", "button", "switch", "check-box",
                "combo-box", "menu-item", "radio-button", "row", "tab",
                "page-tab", "link", "entry", "slider"}


def _count_bucket(n):
    if n <= 3:
        return str(n)
    if n <= 10:
        return "4-10"
    if n <= 30:
        return "11-30"
    return "30+"


def _is_scroll_container(cc):
    if not cc:
        return False
    return any(h in cc for h in SCROLL_CONTAINER_HINTS)


def _name_contrib(e):
    tag = (e.get("tag") or "").lower()
    if tag in _NAME_STABLE:
        return e.get("name", "")
    return ""


def skeleton_id(node):
    """Candidate state-id: scroll-container rows -> coarse per-container sig."""
    fixed = []                      # non-scroll elements: verbatim (tag,name)
    cont_counter = Counter()        # scroll-container key -> row count
    for e in node["elements"]:
        cc = e.get("container_chain")
        if _is_scroll_container(cc):
            cont_counter[cc] += 1
        else:
            fixed.append((e.get("tag", ""), _name_contrib(e)))
    canonical = sorted(fixed)
    for cc, cnt in sorted(cont_counter.items()):
        canonical.append(("__scroll__", cc, _count_bucket(cnt)))
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def uids(n):
    return {e.get("global_uid", "") for e in n["elements"] if e.get("global_uid")}


def main():
    pairs = []
    for gp in ROOT.glob("result_android*/gen_data/*/graphs/*_graph.json"):
        g = json.load(open(gp, encoding="utf-8"))
        nodes = g["nodes"]
        for a, b in combinations(nodes, 2):
            if a["state_id"] == b["state_id"]:
                continue
            ua, ub = uids(a), uids(b)
            if len(ua) < 2 or len(ub) < 2:
                continue
            j = len(ua & ub) / len(ua | ub)
            if j >= 0.5 and len(ua) != len(ub):
                pairs.append((j, a, b, gp))

    print("=== SAME-PAGE pairs: do they now MERGE under candidate id? ===\n")
    merged = same = 0
    for j, a, b, gp in pairs:
        # only meaningful where diff is inside scroll containers
        sa, sb = skeleton_id(a), skeleton_id(b)
        ok = sa == sb
        cc_diff = any(_is_scroll_container(e.get("container_chain"))
                      for e in a["elements"] + b["elements"])
        if cc_diff:
            same += 1
            merged += int(ok)
            tag = "MERGED ✓" if ok else "still split ✗"
            print(f"  j={j:.2f} {a['state_id'][:10]}/{b['state_id'][:10]} -> {tag}  ({sa[:8]} / {sb[:8]})")
    print(f"\nscroll-container split pairs: {same}, merged by candidate: {merged}")

    # Safety: ensure genuinely different pages DON'T collide under candidate id
    print("\n=== COLLISION CHECK: distinct real pages must keep distinct ids ===")
    for gp in ROOT.glob("result_android*/gen_data/*/graphs/*_graph.json"):
        g = json.load(open(gp, encoding="utf-8"))
        by_skel = {}
        collisions = 0
        for n in g["nodes"]:
            s = skeleton_id(n)
            by_skel.setdefault(s, []).append(n["state_id"])
        for s, ids in by_skel.items():
            # different original ids now sharing a skeleton id
            uniq = set(ids)
            if len(uniq) > 1:
                # check they're actually same page via uid jaccard
                collisions += 1
        if collisions:
            print(f"  {gp.parent.parent.parent.parent.name}: {collisions} skeleton-id groups w/ >1 original id")


if __name__ == "__main__":
    main()
