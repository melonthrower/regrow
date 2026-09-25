"""离线轨迹质量检验器 (trajectory QC).

判别式判定一条已采集轨迹是否"合格"，专治逐步注解被串号污染骗过的盲点
(见 design_decisions / 记忆 trajectory-qc-gap、mobile-traj-contamination)。

两层，便宜→贵：

  Layer 0  完整性 & 启发式 (零 token, 确定性)
    - 跨 episode 帧哈希查重: 某帧字节出现在别的 episode(且非"通用页"=出现在 >N
      条里的主页/空白页) -> frame_contamination。
    - 廉价信号: no-op 步占比 / final_status=impossible 却 scenario_success=true。

  Layer 1  判别式逐步 VLM (只对"像素确有变化"的步跑)
    把 agent 的 thinking + action + 前/后截图喂给 VLM, 让它判别(不是描述):
      transition_plausible  : 在同一应用里, 对 BEFORE 做该动作能否得到 AFTER?
                              两张是毫无因果的不同页面(Wi-Fi 跳 Chrome) -> false
      screen_matches_intent : AFTER 画面内容是否还属于 intent 所说的任务/主题?
      intent_achieved       : 实际 BEFORE->AFTER 变化是否达成了 thinking 的意图?
    —— 关键: 在"最终存盘的 stepNN.png"上离线重跑, 而非采集时(采集时 reverse
       读到的帧可能与存盘帧不是同一张, get_screenshot 并发不稳)。

判决: 任一 frame_contamination 或 transition_plausible=false -> 不合格。

用法:
  export PYTHONPATH='.;OSWorld'; export DASHSCOPE_API_KEY=...
  python tools/trajectory_qc.py <collections根 或 含 episodes/ 的目录> \
      [--limit N] [--no_vlm] [--model Qwen|Doubao] [-o qc_report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw


# ── episode 发现 & 帧解析 ───────────────────────────────────────────────

def find_episodes(root: Path) -> List[Path]:
    """返回所有含 trajectory.json 的 episode 目录。"""
    if (root / "trajectory.json").exists():
        return [root]
    eps = sorted(p.parent for p in root.rglob("trajectory.json"))
    return eps


def _load(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _parse_action(st: Dict[str, Any]) -> Dict[str, Any]:
    aj = st.get("action_json")
    x = y = None
    text = ""
    atype = st.get("action") or ""
    if aj:
        try:
            a = json.loads(aj) if isinstance(aj, str) else aj
            if isinstance(a, list):
                a = a[0] if a else {}
            p = a.get("parameters", {}) or {}
            x, y = p.get("x"), p.get("y")
            text = p.get("text", "")
            atype = a.get("action_type", atype)
        except Exception:
            pass
    g = st.get("grounding", {}) or {}
    if x is None and isinstance(g.get("element_center"), dict):
        x, y = g["element_center"].get("x"), g["element_center"].get("y")
    return {"type": atype, "x": x, "y": y, "text": text}


# ── Layer 0: 哈希污染 + 启发式 ──────────────────────────────────────────

def build_hash_index(eps: List[Path]) -> Dict[str, List[str]]:
    """md5 -> [ "<ep_name>/<frame>" ]，跨所有 episode。"""
    idx: Dict[str, List[str]] = defaultdict(list)
    for ep in eps:
        ss = ep / "screenshots"
        if not ss.is_dir():
            continue
        for f in ss.glob("*.png"):
            idx[_md5(f)].append(f"{ep.name}/{f.name}")
    return idx


def layer0(ep: Path, hash_idx: Dict[str, List[str]],
           generic_min_eps: int) -> Dict[str, Any]:
    tj = _load(ep / "trajectory.json")
    meta = tj.get("meta", {}) if isinstance(tj, dict) else {}
    if (ep / "meta.json").exists():
        try:
            meta = {**meta, **_load(ep / "meta.json")}
        except Exception:
            pass
    steps = tj.get("steps", []) if isinstance(tj, dict) else tj

    # 污染: 本 episode 的帧与别的 episode 字节相同, 且共享面不广(非通用页)
    contaminated: List[Dict[str, Any]] = []
    ss = ep / "screenshots"
    if ss.is_dir():
        for f in sorted(ss.glob("*.png")):
            owners = hash_idx.get(_md5(f), [])
            other_eps = sorted({o.split("/")[0] for o in owners} - {ep.name})
            if other_eps and len(other_eps) + 1 < generic_min_eps:
                contaminated.append({"frame": f.name, "also_in": other_eps[:5]})

    # 廉价启发式
    n = len(steps)
    noop = sum(1 for s in steps
               if (s.get("annotation", {}) or {}).get("changed_pixels", 1) == 0
               or (s.get("annotation", {}) or {}).get("had_effect") is False)
    flags: List[str] = []
    if meta.get("final_status") == "impossible" and meta.get("scenario_success") is True:
        flags.append("impossible_but_success")
    if n and noop / n >= 0.4:
        flags.append("many_noop_steps")
    return {
        "instruction_id": meta.get("instruction_id", ep.name),
        "instruction": meta.get("instruction", ""),
        "final_status": meta.get("final_status", ""),
        "scenario_success": meta.get("scenario_success"),
        "num_steps": n,
        "noop_steps": noop,
        "contaminated_frames": contaminated,
        "heuristic_flags": flags,
        "_steps": steps,
    }


# ── Layer 1: 判别式逐步 VLM ─────────────────────────────────────────────

QC_PROMPT = """\
You are a STRICT quality inspector for a GUI agent trajectory. I show you ONE step.

The agent's stated intent (its own thinking): {thinking}
The action it executed: {action}{coord}{text}
This action is a click: {is_click}
App: {app}

Two screenshots are provided:
  - BEFORE (if a click, a RED CIRCLE marks exactly where the click landed)
  - AFTER

Judge ONLY from the two screenshots + the intent + the action. Respond with JSON
(no markdown fences):
{{
  "click_hits_intended_target": true/false/null,
  "transition_plausible": true/false,
  "screen_matches_intent": true/false,
  "intent_achieved": true/false,
  "reason": "one short sentence of evidence"
}}

Rules — be skeptical, do NOT rationalize:
- click_hits_intended_target: ONLY for click actions. On the BEFORE screen, is the
  RED CIRCLE sitting on the UI element that the intent names/implies (e.g. intent
  says "click Sound" and the circle is on the 'Sound' row)? Set false if the circle
  is clearly on a DIFFERENT control than the intent names (e.g. intent says 'Sound'
  but the circle is on 'Display'). Set null if this is not a click, there is no
  marker, or the intended element is not visible on the BEFORE screen.
- transition_plausible: could the AFTER screen plausibly result from performing
  THIS action on the BEFORE screen WITHIN THE SAME APP? If BEFORE and AFTER look
  like unrelated pages with no causal link (e.g. a Wi-Fi settings page in BEFORE
  but a totally different app/page in AFTER that one tap could not reach), set
  false. Do NOT invent a story to connect them.
- screen_matches_intent: does the AFTER screen's content still belong to the same
  task/topic the intent is about? (false if intent is about, say, Wi-Fi metering
  but the screen shows an unrelated feature like a sleep schedule or a browser).
- intent_achieved: did the actual BEFORE->AFTER change accomplish the stated intent?
- Ignore clock / status-bar / cursor / wallpaper differences.
"""


def _img_np(p: Path, mark: Optional[Tuple[int, int]] = None) -> Optional[np.ndarray]:
    if not p.exists():
        return None
    im = Image.open(p).convert("RGB")
    if mark and mark[0] is not None and mark[1] is not None:
        d = ImageDraw.Draw(im)
        x, y = int(mark[0]), int(mark[1])
        r = max(12, im.size[0] // 60)
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 0, 0), width=4)
    return np.array(im)


def _parse_json(txt: str) -> Optional[Dict[str, Any]]:
    if not txt:
        return None
    s = txt.strip()
    if "```" in s:
        s = s.split("```")[1] if s.count("```") >= 2 else s
        s = s.replace("json", "", 1).strip() if s.lower().startswith("json") else s
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s[i:j + 1])
        except Exception:
            return None
    return None


def layer1(ep: Path, l0: Dict[str, Any], agent, app: str,
           max_steps: int) -> List[Dict[str, Any]]:
    steps = l0["_steps"]
    ss = ep / "screenshots"
    frames = [s.get("frame", "") for s in steps]
    out: List[Dict[str, Any]] = []
    judged = 0
    for k, st in enumerate(steps):
        ann = st.get("annotation", {}) or {}
        px = ann.get("changed_pixels", None)
        # 像素已知无变化 -> 生效=否, 无需 VLM (连贯判断只在"确有变化"的步有意义)
        if px == 0 or ann.get("had_effect") is False:
            out.append({"i": k, "skipped": "no_pixel_change", "effective": False})
            continue
        if judged >= max_steps:
            out.append({"i": k, "skipped": "max_steps"})
            continue
        before_f = ss / frames[k] if frames[k] else None
        nxt = frames[k + 1] if k + 1 < len(frames) else "final.png"
        after_f = ss / nxt
        act = _parse_action(st)
        atype = (act["type"] or "").upper()
        is_click = ("CLICK" in atype or atype in ("TAP", "DOUBLE_CLICK",
                    "LEFT_SINGLE")) and act["x"] is not None
        before = _img_np(before_f, (act["x"], act["y"]) if is_click else None) if before_f else None
        after = _img_np(after_f) if after_f else None
        if before is None or after is None:
            out.append({"i": k, "skipped": "missing_frame"})
            continue
        prompt = QC_PROMPT.format(
            thinking=(st.get("thinking") or "(none)")[:400],
            action=act["type"],
            coord=f" @({act['x']},{act['y']})" if act["x"] is not None else "",
            text=f" text='{act['text']}'" if act["text"] else "",
            is_click="yes" if is_click else "no",
            app=app or "unknown",
        )
        try:
            resp, *_ = agent.predict_mm(prompt, [before, after])
            v = _parse_json(resp) or {}
        except Exception as e:
            out.append({"i": k, "vlm_error": str(e)[:120]})
            continue
        judged += 1
        out.append({
            "i": k,
            "thinking": (st.get("thinking") or "")[:90],
            "action": act["type"],
            "is_click": is_click,
            "click_hits_intended_target": v.get("click_hits_intended_target"),
            "transition_plausible": v.get("transition_plausible"),
            "screen_matches_intent": v.get("screen_matches_intent"),
            "intent_achieved": v.get("intent_achieved"),
            "reason": v.get("reason", ""),
        })
    return out


# ── 判决聚合 ────────────────────────────────────────────────────────────

def verdict(l0: Dict[str, Any], l1: List[Dict[str, Any]]) -> Dict[str, Any]:
    reasons: List[str] = []
    bad_trans = [s for s in l1 if s.get("transition_plausible") is False]
    vlm_ran = bool(l1)
    # Layer0 哈希共享帧极易误报(共享主页/同分钟状态栏时钟/no-op 重复帧字节相同)。
    # 真污染以 VLM transition_plausible 为准; 哈希仅当没跑 VLM 时才当硬信号, 否则只
    # 作 contaminated_frames 线索保留, 不进 disqualify。
    hash_contam = bool(l0["contaminated_frames"]) and not vlm_ran
    if hash_contam:
        reasons.append(f"frame_contamination({len(l0['contaminated_frames'])})")
    miss = [s for s in l1 if s.get("click_hits_intended_target") is False]
    off_topic = [s for s in l1 if s.get("screen_matches_intent") is False]
    decision_err = [s for s in l1 if s.get("click_hits_intended_target") is True
                    and s.get("intent_achieved") is False]
    if bad_trans:
        reasons.append(f"incoherent_transition({len(bad_trans)})")
    if miss:
        reasons.append(f"grounding_miss({len(miss)})")
    if off_topic:
        reasons.append(f"topic_drift({len(off_topic)})")
    if "impossible_but_success" in l0["heuristic_flags"]:
        reasons.append("mislabeled_success")

    # severity: 取最重一档 (越靠前越重)。决定"是否进正样本 / 是否重采"。
    n_clicks = sum(1 for s in l1 if s.get("is_click"))
    if bad_trans or hash_contam:
        severity = "contaminated"        # 数据损坏 -> 重采(系统性)
    elif miss:
        severity = "grounding_miss"      # 坐标落歪 -> 误点率高=系统性重采,低=标记
    elif decision_err or off_topic:
        severity = "decision_error"      # 想错了 -> 标记/负样本,不重采
    elif l0["noop_steps"] and l0["num_steps"] and l0["noop_steps"] / l0["num_steps"] >= 0.5:
        severity = "noop_spin"           # 空转 -> 过滤/修 finalize
    else:
        severity = "ok"
    qualified = severity == "ok"
    return {
        "instruction_id": l0["instruction_id"],
        "instruction": l0["instruction"][:80],
        "qualified": qualified,
        "severity": severity,
        "recollect": severity == "contaminated",  # grounding_miss 由批量误点率决定
        "disqualify_reasons": reasons,
        "bad_steps": sorted({s["i"] for s in bad_trans + miss + off_topic}),
        "grounding_miss_steps": sorted(s["i"] for s in miss),
        "click_steps": n_clicks,
        "contaminated_frames": l0["contaminated_frames"],
        "heuristic_flags": l0["heuristic_flags"],
        "num_steps": l0["num_steps"],
        "noop_steps": l0["noop_steps"],
        "step_judgements": l1,
    }


# ── 主程序 ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="离线轨迹质量检验器")
    ap.add_argument("path", help="collections 根 或 含 episodes/ 的目录")
    ap.add_argument("--limit", type=int, default=0, help="只看前 N 条 (0=全部)")
    ap.add_argument("--no_vlm", action="store_true", help="只跑 Layer 0 (零 token)")
    ap.add_argument("--model", default="Qwen", choices=["Qwen", "Doubao"])
    ap.add_argument("--max_steps_vlm", type=int, default=20, help="每条最多判几步")
    ap.add_argument("--generic_min_eps", type=int, default=4,
                    help="帧出现在 >=该数 episode 视为通用页, 不算污染")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    root = Path(args.path)
    eps = find_episodes(root)
    if args.limit:
        eps = eps[:args.limit]
    if not eps:
        print(f"[err] {root} 下没有 episode")
        sys.exit(1)
    print(f"[qc] {len(eps)} episodes under {root}")

    print("[qc] Layer 0: hashing frames for cross-episode contamination ...")
    hash_idx = build_hash_index(eps)

    agent = None
    if not args.no_vlm:
        sys.path.insert(0, str(Path.cwd()))
        from gui_rewalk.env.gui_gen_agent import GUIGenAgent
        ver = "qwen3.7-plus" if args.model == "Qwen" else "doubao-seed-1-8-251228"
        agent = GUIGenAgent(model=args.model, model_version=ver, max_tokens=600,
                            temperature=0.0, observation_type="screenshot",
                            max_retry=2, use_ark=(args.model != "Qwen"))
        print(f"[qc] Layer 1 VLM judge = {args.model}/{ver}")

    reports = []
    for ep in eps:
        l0 = layer0(ep, hash_idx, args.generic_min_eps)
        app = l0.get("final_status") and ""  # app from meta if present
        try:
            app = _load(ep / "meta.json").get("app", "") if (ep / "meta.json").exists() else ""
        except Exception:
            app = ""
        l1 = layer1(ep, l0, agent, app, args.max_steps_vlm) if agent else []
        v = verdict(l0, l1)
        reports.append(v)
        print(f"  [{v['severity']:>13}] {v['instruction_id']:>10}  "
              f"{','.join(v['disqualify_reasons']) or 'qualified'}"
              f"   steps={v['num_steps']} noop={v['noop_steps']}")

    out = Path(args.out) if args.out else (root / "qc_report.json")
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    # 汇总: severity 分布 + grounding 误点率(系统性 vs 偶发的判据)
    from collections import Counter
    sev = Counter(r["severity"] for r in reports)
    nbad = sum(1 for r in reports if not r["qualified"])
    tot_clicks = sum(r["click_steps"] for r in reports)
    tot_miss = sum(len(r["grounding_miss_steps"]) for r in reports)
    rate = (tot_miss / tot_clicks * 100) if tot_clicks else 0.0
    print(f"\n[qc] severity: " + ", ".join(f"{k}={v}" for k, v in sev.most_common()))
    print(f"[qc] grounding 误点率: {tot_miss}/{tot_clicks} click 步 = {rate:.1f}% "
          f"({'系统性,建议修grounding+重采' if rate >= 15 else '偏偶发,标记过滤即可'})")
    print(f"[qc] {nbad}/{len(reports)} disqualified -> {out}")


if __name__ == "__main__":
    main()
