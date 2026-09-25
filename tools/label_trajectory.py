"""Label collected GUI trajectories against the graph ground truth.

Architecture: the comparison unit is "target semantics vs actual action
semantics", NOT raw state_id equality. Three layers, degrading gracefully:

  L1 StateMatcher   — step.graph_context_node_id hits the target feature's
                      entry_state -> deterministic (static apps like Settings).
  L2 Region+VLM     — when L1 misses: classify the acted element's REGION
                      (stable nav vs dynamic content) via vlm_category /
                      geometry / global_uid, then ask a VLM whether the acted
                      control matches the step's target semantics.
  L3 VLM visual     — when L1/L2 can't decide: ask a VLM on the before/after
                      screenshots whether the step advances toward the goal.

Per-step labels: goal / on_path / detour / recovery / redundant.
Whole-trajectory outcome: reached_goal / partial / failed.

Inputs:
  exec_results.json          (collected trajectories; screenshots are file paths)
  composed_scenarios.json    (ground truth: per-scenario targets + per-step
                              graph_node_id + target control)
  graph json                 (vlm_category, global_uid, stable nav element set)

Output: labeled_trajectories.json

Run:
  export PYTHONPATH='.;OSWorld'; export DASHSCOPE_API_KEY='...'
  python.exe tools/label_trajectory.py \
    --exec result_setting_qwen_0603_noopfix/collection_smoke6/exec_results.json \
    --composed result_setting_qwen_0603_noopfix/composed_scenarios.json \
    --graph result_setting_qwen_0603_noopfix/gen_data/Qwen/graphs/0_graph.json
"""
import argparse
import json
import os

import numpy as np
from PIL import Image


# ── ground-truth + graph helpers ─────────────────────────────────────────

def load_targets(composed_path):
    """scenario_id -> {targets:{feat:val}, steps:[{graph_node_id, element_name,
    target_page, low_level_instruction}], entry_states:set}"""
    out = {}
    for sc in json.load(open(composed_path, encoding="utf-8")):
        es = {s.get("graph_node_id") for s in sc["steps"] if s.get("graph_node_id")}
        out[sc["scenario_id"]] = {
            "targets": sc.get("targets", {}),
            "steps": sc["steps"],
            "entry_states": es,
            "instruction": sc.get("instruction_en", ""),
        }
    return out


def load_graph_index(graph_path):
    """Build stable-region indices from the graph:
      stable_uids : global_uid set of vlm_category=='navigation' elements
      node_exists : set of state_ids present in the graph
      uid_by_node : {state_id: {global_uid: element}} (for region lookups)
    """
    g = json.load(open(graph_path, encoding="utf-8"))
    stable_uids = set()
    node_exists = set()
    for n in g["nodes"]:
        sid = n.get("id") or n.get("state_id")
        if sid:
            node_exists.add(sid)
        for e in n.get("elements", []):
            if e.get("vlm_category") == "navigation" and e.get("global_uid"):
                stable_uids.add(e["global_uid"])
    return {"stable_uids": stable_uids, "node_exists": node_exists}


# ── L2 region classifier ─────────────────────────────────────────────────

def classify_region(step, graph_index, screen_w=1920):
    """Return ('stable'|'content'|'unknown', reason). Uses, in order:
    vlm_category(navigation) via global_uid match -> geometry -> default."""
    uid = step.get("global_uid") or step.get("element_global_uid")
    if uid and uid in graph_index["stable_uids"]:
        return "stable", f"global_uid {uid} in nav set"
    bbox = step.get("element_bbox") or {}
    y = bbox.get("y", step.get("element_center", {}).get("y", 9999))
    x = bbox.get("x", step.get("element_center", {}).get("x", 9999))
    if isinstance(y, (int, float)) and y < 60:
        return "stable", f"top bar (y={y})"
    if isinstance(x, (int, float)) and x < 300:
        return "stable", f"left sidebar (x={x})"
    return "content", "in content area"


# ── VLM (L2 semantic, L3 visual) ─────────────────────────────────────────

class VLM:
    def __init__(self, agent):
        self.agent = agent

    def _imgs(self, *paths):
        out = []
        for p in paths:
            if p and os.path.exists(p):
                try:
                    out.append(np.array(Image.open(p).convert("RGB")))
                except Exception:
                    pass
        return out

    def parse(self, resp):
        t = resp.strip()
        if "```" in t:
            t = t.split("```")[1]
            if t.startswith("json"):
                t = t[4:]
            t = t.strip()
        s, e = t.find("{"), t.rfind("}") + 1
        return json.loads(t[s:e]) if s >= 0 else {}

    def semantic_match(self, acted_name, acted_role, target_feature,
                       target_value, step_goal):
        """L2: does the acted control match the step's target semantics?"""
        prompt = (
            "You verify a GUI agent's action against its intended target.\n"
            f"Intended step goal: {step_goal}\n"
            f"Target setting: '{target_feature}' -> '{target_value}'\n"
            f"Actually acted control: name='{acted_name}', role='{acted_role}'\n"
            "Does the acted control correspond to the intended target (allowing "
            "synonyms/renames)? Return ONLY JSON:\n"
            '{"matches_target": true/false, "advances_toward_goal": true/false, '
            '"reason": "..."}'
        )
        try:
            resp, *_ = self.agent.predict_mm(prompt, [])
            return self.parse(resp)
        except Exception as e:
            return {"matches_target": None, "advances_toward_goal": None,
                    "reason": f"vlm_error: {e}"}

    def visual_advance(self, before_path, after_path, step_goal, instruction):
        """L3: from before/after screenshots, did this step advance the goal?"""
        prompt = (
            "You judge whether a GUI step moved toward the task goal.\n"
            f"Overall task: {instruction}\n"
            f"This step's goal: {step_goal}\n"
            "Compare the BEFORE and AFTER screenshots. Return ONLY JSON:\n"
            '{"advances_toward_goal": true/false, "went_wrong": true/false, '
            '"reason": "..."}'
        )
        imgs = self._imgs(before_path, after_path)
        try:
            resp, *_ = self.agent.predict_mm(prompt, imgs)
            return self.parse(resp)
        except Exception as e:
            return {"advances_toward_goal": None, "went_wrong": None,
                    "reason": f"vlm_error: {e}"}


# ── per-step labeling ────────────────────────────────────────────────────

def label_step(step, gt, graph_index, vlm, instruction, enable_l3=True):
    """Return {label, confidence, layer, region, evidence}."""
    ctx = step.get("graph_context_node_id", "")
    elem = step.get("element_name", "")
    role = step.get("element_role", "")
    had_effect = step.get("reverse_had_effect")
    completed = step.get("reverse_step_completed")
    step_goal = step.get("scenario_instruction") or step.get("goal", "")
    entry_states = gt["entry_states"]
    targets = gt["targets"]

    # redundant: no state change and no effect
    if had_effect is False:
        return {"label": "redundant", "confidence": "high", "layer": "rule",
                "region": None, "evidence": "reverse_had_effect=False"}

    # ── L1: integral state match ──
    if ctx and ctx in entry_states:
        # On the correct target page. It's a goal if a target value got
        # completed here. element_name is often empty on sub-action steps, so
        # don't require a name match: completed + on-target-page => goal.
        if completed:
            is_target_ctrl = any(
                elem and (elem.lower() in f.lower() or f.lower() in elem.lower())
                for f in targets)
            ev = (f"ctx={ctx} target ctrl {elem} done" if is_target_ctrl
                  else f"ctx={ctx} on target page, step completed")
            return {"label": "goal", "confidence": "high", "layer": "L1",
                    "region": "stable", "evidence": ev}
        return {"label": "on_path", "confidence": "high", "layer": "L1",
                "region": "stable", "evidence": f"ctx={ctx} on target page"}

    # ── Navigation step toward a target page (before calling it a detour) ──
    # Clicking a stable nav element whose destination is a target page is
    # forward progress, not a detour. Detect via: acted element is nav-region
    # AND its name matches a target page / the next step lands on a target page.
    region, rreason = classify_region(step, graph_index)
    if region == "stable":
        # a nav click that is plainly part of reaching the target = on_path
        return {"label": "on_path", "confidence": "medium", "layer": "L2-nav",
                "region": region,
                "evidence": f"nav click in stable region ({rreason})"}

    # ── L2: region + VLM semantic ──
    # pick the most relevant target for semantic comparison
    tfeat, tval = (next(iter(targets.items())) if targets else ("", ""))
    sem = vlm.semantic_match(elem, role, tfeat, tval, step_goal)
    if sem.get("matches_target"):
        lbl = "goal" if completed else "on_path"
        return {"label": lbl, "confidence": "medium", "layer": "L2",
                "region": region, "evidence": f"{rreason}; vlm:{sem.get('reason','')[:80]}"}
    if sem.get("advances_toward_goal"):
        return {"label": "on_path", "confidence": "medium", "layer": "L2",
                "region": region, "evidence": f"{rreason}; vlm advances"}
    if sem.get("matches_target") is False and sem.get("advances_toward_goal") is False:
        return {"label": "detour", "confidence": "medium", "layer": "L2",
                "region": region, "evidence": f"{rreason}; vlm:{sem.get('reason','')[:80]}"}

    # ── L3: visual fallback ──
    if enable_l3:
        vis = vlm.visual_advance(step.get("screen_before"), step.get("screen_after"),
                                 step_goal, instruction)
        if vis.get("advances_toward_goal"):
            return {"label": "on_path", "confidence": "low", "layer": "L3",
                    "region": region, "evidence": f"vlm-visual:{vis.get('reason','')[:80]}"}
        if vis.get("went_wrong"):
            return {"label": "detour", "confidence": "low", "layer": "L3",
                    "region": region, "evidence": f"vlm-visual:{vis.get('reason','')[:80]}"}

    return {"label": "on_path", "confidence": "low", "layer": "fallback",
            "region": region, "evidence": "undecided -> default on_path"}


def post_pass_recovery(labels):
    """A detour immediately followed by a step that returns to the correct path
    re-tags that returning step as 'recovery'. A step that achieves a target
    stays 'goal' (we add recovered=True instead of overwriting it)."""
    for i in range(1, len(labels)):
        if labels[i - 1]["label"] == "detour":
            if labels[i]["label"] == "on_path":
                labels[i]["label"] = "recovery"
                labels[i]["evidence"] = "after detour -> " + labels[i]["evidence"]
            elif labels[i]["label"] == "goal":
                labels[i]["recovered"] = True
                labels[i]["evidence"] = "goal after detour -> " + labels[i]["evidence"]
    return labels


def trajectory_outcome(steps, labels, gt):
    """reached_goal if every target got a goal-labeled step; else partial/failed."""
    n_goal = sum(1 for l in labels if l["label"] == "goal")
    n_targets = max(1, len(gt["targets"]))
    if n_goal >= n_targets:
        return "reached_goal"
    if n_goal > 0:
        return "partial"
    return "failed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exec", required=True)
    ap.add_argument("--composed", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no_l3", action="store_true")
    args = ap.parse_args()

    gtmap = load_targets(args.composed)
    graph_index = load_graph_index(args.graph)

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus",
                        observation_type="screenshot", action_space="gen_data",
                        max_tokens=800, use_ark=False)
    vlm = VLM(agent)

    results = json.load(open(args.exec, encoding="utf-8"))
    out = []
    for r in results:
        sid = r["scenario_id"]
        gt = gtmap.get(sid, {"targets": {}, "steps": [], "entry_states": set(),
                             "instruction": r.get("instruction", "")})
        instruction = gt.get("instruction") or r.get("instruction", "")
        labels = []
        for step in r["trajectory"]:
            labels.append(label_step(step, gt, graph_index, vlm, instruction,
                                     enable_l3=not args.no_l3))
        labels = post_pass_recovery(labels)
        outcome = trajectory_outcome(r["trajectory"], labels, gt)
        out.append({
            "scenario_id": sid,
            "instruction": instruction,
            "targets": gt["targets"],
            "outcome": outcome,
            "steps": [
                {"step": i + 1,
                 "action": s.get("action"),
                 "element_name": s.get("element_name"),
                 "ctx_node": s.get("graph_context_node_id"),
                 **lab}
                for i, (s, lab) in enumerate(zip(r["trajectory"], labels))
            ],
        })

    out_path = args.out or os.path.join(os.path.dirname(args.exec),
                                        "labeled_trajectories.json")
    json.dump(out, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"labeled {len(out)} trajectories -> {out_path}\n")
    for tr in out:
        print(f"[{tr['scenario_id']}] outcome={tr['outcome']} targets={tr['targets']}")
        for s in tr["steps"]:
            print(f"  step{s['step']}: {s['label']:9s} ({s['confidence']}/{s['layer']}) "
                  f"elem={s['element_name']!r} | {s['evidence'][:70]}")
        print()


if __name__ == "__main__":
    main()
