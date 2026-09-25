"""Deterministically inject state-dependent preconditions into an existing
long-chain instruction set (R6).

Why: the precondition refs are normally inserted by
``CapabilityInstructionGenerator._resolve_refs`` at *generation* time. The
hand-cleaned long-chain set was produced *before* the graph was enriched with
preconditions, so its capability_refs lack the gate sub-goals. To keep the SAME
16 instructions (clean A/B vs the R5 baseline) but add the gates, this tool
walks each instruction's capability_refs and, for any ref whose capability in
the *enriched* graph carries an applicable precondition, inserts the synthetic
"[前置] satisfy the gate first" ref immediately before it.

No model / VM. Pure post-processing. Idempotent (won't double-insert a gate
that is already present right before its target).

Usage:
  python tools/inject_preconditions.py --node_dir <enriched nodes dir> \
      --in _instructions_longchain_clean.json --out _instructions_longchain_precond.json
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui_rewalk.src.core.scenario.capability_instruction_gen import (  # noqa: E402
    CapabilityInstructionGenerator,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node_dir", required=True,
                    help="enriched graph nodes dir (page_capabilities.json must "
                         "already carry 'precondition' fields)")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    gen = CapabilityInstructionGenerator(args.node_dir, agent=None, graph=None)
    n = gen.load_capabilities()
    print(f"loaded {n} capabilities from enriched graph")

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("instructions", [])

    def _is_same_gate(ref: dict, pre_d: dict, gate_eids: set) -> bool:
        """A ref already in the instruction that targets the SAME gate control.
        Matched by name, by the unlock state appearing among its element_map
        keys, or by sharing a grounding element id with the gate (robust across
        node-variants of the same logical control)."""
        if ref.get("name") == pre_d.get("name"):
            return True
        state = pre_d.get("value", "")
        if state and state in (ref.get("element_map") or {}):
            return True
        eids = set(ref.get("elements") or [])
        for vs in (ref.get("element_map") or {}).values():
            eids.update(vs or [])
        return bool(eids & gate_eids)

    total_injected = 0
    total_filled = 0
    for it in items:
        refs = it.get("capability_refs", [])
        iid = it.get("instruction_id") or it.get("id")
        new_refs = []
        for r in refs:
            name = r.get("name", "")
            value = r.get("value", "")
            cap = gen._by_key.get(name)
            if cap is not None and getattr(cap, "precondition", None):
                pre = gen._make_precondition_ref(cap, value)
                if pre is not None:
                    pre_d = pre.to_dict()
                    state = pre_d.get("value", "")
                    gate_eids = set(pre_d.get("elements") or [])
                    for vs in (pre_d.get("element_map") or {}).values():
                        gate_eids.update(vs or [])
                    # Does the instruction ALREADY contain a ref to this gate?
                    existing = next(
                        (x for x in it["capability_refs"]
                         if x is not r and _is_same_gate(x, pre_d, gate_eids)),
                        None)
                    already_emitted = any(
                        x.get("is_precondition") and _is_same_gate(x, pre_d, gate_eids)
                        for x in new_refs)
                    if existing is not None:
                        # the human chain already steps this control; just make
                        # sure it actually SETS the unlock value (it was empty),
                        # rather than inserting a duplicate.
                        if not str(existing.get("value") or "").strip():
                            existing["value"] = state
                            if state in (existing.get("element_map") or {}):
                                existing["elements"] = list(
                                    existing["element_map"][state])
                            total_filled += 1
                            print(f"  [{iid}] ~填值 {existing.get('name')} -> "
                                  f"{state}  (已有步骤,补解锁值; 目标 {name})")
                    elif not already_emitted:
                        new_refs.append(pre_d)
                        total_injected += 1
                        print(f"  [{iid}] +前置 {pre_d.get('name')} -> "
                              f"{state}  (解锁 {name} -> {value})")
            new_refs.append(r)
        it["capability_refs"] = new_refs

    Path(args.out).write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ninjected {total_injected} precondition step(s); "
          f"wrote {len(items)} instructions -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
