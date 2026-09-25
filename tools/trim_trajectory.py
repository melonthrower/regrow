"""事后 trim 工具: 从一条已采集 episode 里剪除"可证死步", 产出 trimmed 副本。

用户明确想要"剪掉不必要的帧", 让轨迹更像人。本工具【不改原始文件】, 只在 episode
目录里另写 `trajectory_trimmed.json` + 重缝的 screenshots 引用 (新 stepNN_trim.png),
并记录 `trimmed_from` / 被剪步数 + 每步原因, 全程可追溯。

剪 (可证死步):
  - no-op WAIT: 无推进 (had_effect=False 且无 step_completed) 的 WAIT。
  - abandoned_search: executor 跨步检测标出的"开了搜索却没用"绕路步 (及其紧邻的、
    为开搜索而发的前置 no-op WAIT)。
  - 连续重复的死点击: had_effect=False 且坐标近重复的 CLICK 族, 同一簇只留 1 个代表。
  - 连续无效的同向 SCROLL: had_effect=False 的滚动死冲, 同一簇只留 1 个代表。
  - 明显震荡 A→B→A 的多余往返: 中间那个把人带回原地的步。

保留 (关键, 别过度剪):
  - 有意义的 exploration→wrong_branch→backtrack→recovery (项目要这个监督信号)。
    只要不是"纯死冲重复", backtrack/recovery 步一律保留。
  - 任何 had_effect=True 且推进子目标 (progress / page_local / step_completed) 的步。
  - 最终 FINISHED / IMPOSSIBLE 终止步 (永不剪)。

剪后:
  - 重缝 frame 链: 每个保留步的 before = 上一保留步的 after (这里 frame 即 before 帧,
    所以重缝 = 重排连续的 stepNN 帧文件 + 重算 step 序号), final 帧保持指向最后保留步
    的结果页。
  - 重算 step 序号 0..N-1。
  - 写 trimmed.meta.trim 记录: trimmed_from, removed (含每步 orig_step + reason),
    kept / removed 计数。

用法:
  python tools/trim_trajectory.py <episode_dir> [--dry-run] [--quiet]
  python tools/trim_trajectory.py <episode_dir>/trajectory.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 阈值 (与 scenario_executor 护栏同口径) ────────────────────────────────
COORD_GRID = 25          # px: 两坐标距离 < 此值视为"同一个地方"
EFFECT_PX_THRESHOLD = 200  # changed_pixels > 此值才算 had_effect (与执行器一致)

CLICK_LIKE = {"CLICK", "LEFT_DOUBLE", "RIGHT_SINGLE"}
TERMINAL = {"FINISHED", "IMPOSSIBLE"}


# ── 字段读取 helpers (兼容轨迹 schema) ────────────────────────────────────
def _ann(step: Dict) -> Dict:
    return step.get("annotation", {}) or {}


def real_action_type(step: Dict) -> str:
    """优先 action_json 里的真实 action_type (顶层 action 可能是渲染用的 CLICK)。"""
    aj = step.get("action_json", "")
    if aj:
        try:
            return (json.loads(aj).get("action_type", "") or "").upper()
        except Exception:
            pass
    return (step.get("action") or "").upper()


def step_coord(step: Dict) -> Optional[Tuple[int, int]]:
    ec = (step.get("grounding") or {}).get("element_center", {})
    if isinstance(ec, dict) and "x" in ec and "y" in ec:
        return int(ec["x"]), int(ec["y"])
    # action_json 兜底
    aj = step.get("action_json", "")
    if aj:
        try:
            p = json.loads(aj).get("parameters", {}) or {}
            x = p.get("x", p.get("x1"))
            y = p.get("y", p.get("y1"))
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                return int(x), int(y)
        except Exception:
            pass
    return None


def had_effect(step: Dict) -> bool:
    a = _ann(step)
    if "had_effect" in a:
        # 仍以像素差为最终口径 (有效但像素未变 = 假阳性)
        px = a.get("changed_pixels")
        if isinstance(px, (int, float)):
            return bool(a["had_effect"]) and px > EFFECT_PX_THRESHOLD
        return bool(a["had_effect"])
    px = int(a.get("changed_pixels", 0) or 0)
    return px > EFFECT_PX_THRESHOLD


def step_completed(step: Dict) -> bool:
    return bool(_ann(step).get("step_completed", False))


def is_abandoned_search(step: Dict) -> bool:
    return bool(_ann(step).get("abandoned_search")
                or step.get("abandoned_search"))


def scroll_dir(step: Dict) -> str:
    aj = step.get("action_json", "")
    if aj:
        try:
            return (json.loads(aj).get("parameters", {}) or {}).get(
                "direction", "") or ""
        except Exception:
            pass
    return ""


def near(a: Optional[Tuple[int, int]], b: Optional[Tuple[int, int]]) -> bool:
    if a is None or b is None:
        return False
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 < COORD_GRID


# ── 核心: 计算保留 / 剪除决策 ─────────────────────────────────────────────
def plan_trim(steps: List[Dict]) -> List[Dict]:
    """返回与 steps 等长的决策列表: [{keep, reason}]。reason 仅在剪除时有意义。"""
    n = len(steps)
    decisions = [{"keep": True, "reason": ""} for _ in range(n)]

    def drop(i: int, reason: str):
        decisions[i]["keep"] = False
        decisions[i]["reason"] = reason

    for i, s in enumerate(steps):
        act = real_action_type(s)
        is_terminal = act in TERMINAL
        if is_terminal:
            continue  # 终止步永不剪

        # 1) abandoned_search 绕路步 + 其前置 no-op WAIT。
        if is_abandoned_search(s):
            drop(i, "abandoned_search detour (opened search, never queried)")
            # 紧邻在前的、为开搜索而发的 no-op WAIT 一并剪 (eff=False 的 WAIT)。
            j = i - 1
            if (j >= 0 and decisions[j]["keep"]
                    and real_action_type(steps[j]) == "WAIT"
                    and not had_effect(steps[j])
                    and not step_completed(steps[j])):
                drop(j, "no-op WAIT paired with abandoned_search")
            continue

        # 2) no-op WAIT: 无推进的 WAIT (非终止)。
        if act == "WAIT" and not had_effect(s) and not step_completed(s):
            drop(i, "no-op WAIT (no effect, no progress)")
            continue

    # 3) 连续重复死点击 / 死滚动: had_effect=False 的同类近重复簇, 只留首个代表。
    #    扫描【尚未被剪】的步, 按"动作类型 + (点击:近坐标 / 滚动:同方向)"分簇。
    i = 0
    while i < n:
        if not decisions[i]["keep"]:
            i += 1
            continue
        s = steps[i]
        act = real_action_type(s)
        if act in TERMINAL or had_effect(s) or step_completed(s):
            i += 1
            continue
        # 起一个死动作簇 (eff=False)
        if act in CLICK_LIKE:
            ref = step_coord(s)
            j = i + 1
            cluster = [i]
            while j < n:
                if not decisions[j]["keep"]:
                    j += 1
                    continue
                t = steps[j]
                if (real_action_type(t) in CLICK_LIKE
                        and not had_effect(t) and not step_completed(t)
                        and near(step_coord(t), ref)):
                    cluster.append(j)
                    j += 1
                    continue
                break
            if len(cluster) > 1:
                for k in cluster[1:]:
                    drop(k, "redundant dead click (no effect, near-duplicate "
                            "coord)")
            i = cluster[-1] + 1
            continue
        if act == "SCROLL":
            d = scroll_dir(s)
            j = i + 1
            cluster = [i]
            while j < n:
                if not decisions[j]["keep"]:
                    j += 1
                    continue
                t = steps[j]
                if (real_action_type(t) == "SCROLL"
                        and not had_effect(t) and not step_completed(t)
                        and scroll_dir(t) == d):
                    cluster.append(j)
                    j += 1
                    continue
                break
            if len(cluster) > 1:
                for k in cluster[1:]:
                    drop(k, "redundant dead scroll (no effect, same direction)")
            i = cluster[-1] + 1
            continue
        i += 1

    # 4) 震荡 A→B→A: 三个【保留中的】连续 CLICK 族, c0≈c2 且 c1 与之不同 →
    #    中间的 B 把人带去又被 A 带回 = 多余往返, 剪掉 B (保留两端的 A 与去向)。
    #    只在三步都【有效】(否则前面已按死簇处理) 且非终止时触发, 避免误伤死冲。
    kept_clicks = [i for i in range(n)
                   if decisions[i]["keep"]
                   and real_action_type(steps[i]) in CLICK_LIKE
                   and real_action_type(steps[i]) not in TERMINAL]
    for a, b, c in zip(kept_clicks, kept_clicks[1:], kept_clicks[2:]):
        ca, cb, cc = step_coord(steps[a]), step_coord(steps[b]), step_coord(steps[c])
        if near(ca, cc) and not near(ca, cb) and cb is not None:
            # B 是往返中点。仅当 B 没带来真正推进 (非 step_completed) 才剪。
            if not step_completed(steps[b]):
                drop(b, "oscillation midpoint A->B->A (redundant round-trip)")

    return decisions


# ── 输出: 重缝 + 写文件 ───────────────────────────────────────────────────
def build_trimmed(data: Dict, decisions: List[Dict]) -> Tuple[Dict, List[Dict]]:
    """返回 (trimmed_data, removed_records)。重排 step 序号 + frame 引用。"""
    steps = data.get("steps", [])
    kept = [(i, s) for i, s in enumerate(steps) if decisions[i]["keep"]]
    removed = [{"orig_step": i, "action": real_action_type(steps[i]),
                "reason": decisions[i]["reason"]}
               for i, s in enumerate(steps) if not decisions[i]["keep"]]

    new_steps = []
    for new_idx, (orig_idx, s) in enumerate(kept):
        ns = dict(s)  # 浅拷贝, 不动原 dict
        ns["step"] = new_idx
        ns["_orig_step"] = orig_idx
        # 重缝 frame: 旧 frame 文件名 stepNN.png → 新 stepMM_trim.png。
        old_frame = s.get("frame", "")
        if old_frame:
            ns["frame"] = f"step{new_idx:02d}_trim.png"
            ns["_orig_frame"] = old_frame
        new_steps.append(ns)

    meta = dict(data.get("meta", {}))
    meta["num_steps"] = len(new_steps)
    meta["trim"] = {
        "trimmed_from": len(steps),
        "kept": len(new_steps),
        "removed_count": len(removed),
        "removed": removed,
    }
    return {"meta": meta, "steps": new_steps}, removed


def restitch_frames(ep_dir: str, trimmed: Dict, dry_run: bool) -> int:
    """把每个保留步的原 frame 复制成新的 stepNN_trim.png。返回复制成功数。"""
    ss = os.path.join(ep_dir, "screenshots")
    if not os.path.isdir(ss):
        return 0
    copied = 0
    for s in trimmed["steps"]:
        orig = s.get("_orig_frame", "")
        new = s.get("frame", "")
        if not orig or not new:
            continue
        src = os.path.join(ss, orig)
        dst = os.path.join(ss, new)
        if os.path.exists(src):
            if not dry_run:
                shutil.copy(src, dst)
            copied += 1
    return copied


def resolve_episode(path: str) -> Tuple[str, str]:
    """接受 episode 目录或 trajectory.json 路径 → (ep_dir, trajectory.json)。"""
    if os.path.isfile(path) and path.endswith(".json"):
        return os.path.dirname(path), path
    if os.path.isdir(path):
        return path, os.path.join(path, "trajectory.json")
    raise SystemExit(f"not an episode dir or trajectory.json: {path}")


def trim_episode(path: str, dry_run: bool = False,
                 quiet: bool = False) -> Dict:
    ep_dir, traj_path = resolve_episode(path)
    if not os.path.exists(traj_path):
        raise SystemExit(f"trajectory.json not found: {traj_path}")
    data = json.loads(open(traj_path, encoding="utf-8").read())
    steps = data.get("steps", [])
    decisions = plan_trim(steps)
    trimmed, removed = build_trimmed(data, decisions)

    out_path = os.path.join(ep_dir, "trajectory_trimmed.json")
    copied = restitch_frames(ep_dir, trimmed, dry_run)
    if not dry_run:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)

    if not quiet:
        print(f"episode: {ep_dir}")
        print(f"  {len(steps)} steps -> {len(trimmed['steps'])} kept "
              f"({len(removed)} removed), {copied} frames re-stitched"
              + ("  [dry-run]" if dry_run else f"  -> {out_path}"))
        for r in removed:
            print(f"    - removed orig s{r['orig_step']} ({r['action']}): "
                  f"{r['reason']}")
    return {"ep_dir": ep_dir, "original": len(steps),
            "kept": len(trimmed["steps"]), "removed": removed,
            "out_path": out_path if not dry_run else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", help="episode dir or trajectory.json path")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + print plan, write nothing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    trim_episode(args.episode, dry_run=args.dry_run, quiet=args.quiet)


if __name__ == "__main__":
    main()
