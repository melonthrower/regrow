"""Deduplicate capability records across repeated graph nodes.

Repeated traversal states produce the same settings page under several
state_ids (e.g. 5 Notifications nodes). Features are identified by their
member_ids (element_ids are stable in the graph), so two features are THE SAME
feature iff their member_ids sets are equal. We merge those, keeping the list
of entry_states (every state_id where the feature appears) so a later
instruction step knows all the nodes it can be reached from.

Deterministic, no model calls.

Output: capability_records_dedup.json  — one entry per unique feature.
Also prints a readable summary.
"""
import json
from collections import defaultdict

SRC = "result_setting_qwen_0603_noopfix/capability_records.json"
OUT = "result_setting_qwen_0603_noopfix/capability_records_dedup.json"


def feature_key(feat):
    """Identity of a feature.

    element_ids are NOT stable across repeated traversal nodes (the same
    Notifications page gets different element_ids in each state), so member_ids
    can't dedup cross-node repeats. Use (normalized feature name + params) as
    the identity instead — deterministic and matches what a user perceives as
    "the same setting"."""
    name = (feat.get("feature") or "").strip().lower()
    params = tuple(feat.get("params") or [])
    if feat.get("shape") == "multi_dimension":
        # identity from the set of sub-dimension param-tuples (order-independent)
        dims = frozenset(
            (sg.get("dimension", ""), tuple(sg.get("params") or []))
            for sg in feat.get("sub_groups", [])
        )
        return ("multi", name, dims)
    return ("flat", name, params)


def main():
    recs = json.load(open(SRC, encoding="utf-8"))
    merged = {}  # key -> unified feature dict
    for rec in recs:
        sid = rec["state_id"]
        page = rec.get("page_description", "")
        for feat in rec.get("features", []):
            key = feature_key(feat)
            if key not in merged:
                merged[key] = {
                    "feature": feat.get("feature"),
                    "shape": feat.get("shape"),
                    "params": feat.get("params"),
                    "sub_groups": feat.get("sub_groups"),
                    "member_ids": feat.get("member_ids"),
                    "params_incomplete": feat.get("params_incomplete", False),
                    "entry_states": [],
                    "page_descriptions": set(),
                    "name_variants": set(),
                }
            m = merged[key]
            m["entry_states"].append(sid)
            # per-state member_ids: instruction execution needs the element_ids
            # valid in THAT specific node (ids differ per traversal state)
            m.setdefault("member_ids_by_state", {})[sid] = feat.get("member_ids")
            if page:
                m["page_descriptions"].add(page[:60])
            if feat.get("feature"):
                m["name_variants"].add(feat["feature"])

    out = []
    for key, m in merged.items():
        m["page_descriptions"] = sorted(m["page_descriptions"])
        m["name_variants"] = sorted(m["name_variants"])
        m["occurrence_count"] = len(m["entry_states"])
        out.append(m)
    # sort: multi-control features first, then by name
    out.sort(key=lambda f: (-(len(f.get("member_ids") or [])), f.get("feature") or ""))

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    total_raw = sum(len(r.get("features", [])) for r in recs)
    print(f"raw feature instances: {total_raw}  ->  unique features: {len(out)}")
    print(f"(from {len(recs)} page-nodes)\n")
    for f in out:
        nm = f["feature"]
        variants = "" if len(f["name_variants"]) <= 1 else f"  (aka {f['name_variants']})"
        occ = f"x{f['occurrence_count']}" if f["occurrence_count"] > 1 else ""
        shape = f["shape"]
        if shape == "multi_dimension":
            print(f"  [{shape}] {nm} {occ}{variants}")
            for sg in (f.get("sub_groups") or []):
                print(f"        <{sg.get('dimension')}>: {sg.get('params')}")
        else:
            inc = " (incomplete)" if f.get("params_incomplete") else ""
            print(f"  [{shape}] {nm} -> {f.get('params')}{inc} {occ}{variants}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
