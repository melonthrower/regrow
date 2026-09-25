#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
export_sft_dataset.py — 把 collections/ 下采集的轨迹导出成 ms-swift 多模态 SFT 数据集。

每一步 (step) = 一条训练样本:
    system : GUI agent 角色 + 动作空间说明
    user   : <image>当前截图 + 任务指令 + 历史动作摘要 + (可选)页面上下文
    assistant: Thought: {thinking}\nAction: {action_json}

旧格式按 annotation 过滤。视觉采集格式要求任务终验与每步回执成功，保留导航；
直接使用实际执行的单条 primitive 和动作前截图，不拆分缺少中间截图的复合动作。

用法:
    python tools/export_sft_dataset.py \
        --collections collections/OS \
        --out data/sft \
        --val_ratio 0.05

输出:
    data/sft/train.jsonl, data/sft/val.jsonl  (ms-swift messages 格式)
    data/sft/stats.json                        (导出统计)
图片在样本里用绝对路径引用 (不复制), 训练机上路径需一致 —— 见 --image_root_replace。
"""
import argparse
import glob
import io
import json
import os
import random
import sys

# 默认保留的 step_type (任务推进/页内有效操作); 这些是"干净示范"
DEFAULT_KEEP_TYPES = {"progress", "page_local"}
# 终止类动作即使 step_type 不在 KEEP 也要保留 (教模型何时收尾)
TERMINAL_ACTIONS = {"FINISHED", "STEP_DONE"}

SYSTEM_PROMPT = (
    "你是一个 GUI 智能体，通过观察屏幕截图来完成用户指定的操作任务。"
    "每一步你先用一句话思考，然后输出一个动作 JSON。"
    "动作空间: CLICK(x,y) / LEFT_DOUBLE(x,y) / RIGHT_SINGLE(x,y) / "
    "TYPE(text) / HOTKEY(keys) / SCROLL(point,direction,amount) / DRAG(x1,y1,x2,y2) / "
    "WAIT / FINISHED / IMPOSSIBLE(reason)。坐标为截图像素坐标。"
    "输出格式严格为两行:\nThought: <一句话思考>\nAction: <动作 JSON>"
)

ANDROID_ACTIONS = {"click", "long_press", "input_text", "scroll", "navigate_back"}
ANDROID_SYSTEM_PROMPT = (
    "你是一个 Android GUI 智能体，通过观察屏幕截图完成用户任务。"
    "输出动作 JSON 使用 action_type 与平铺参数：click/long_press 使用 x,y；"
    "input_text 使用 x,y,text,clear_text；scroll 使用 x,y,direction,frac；navigate_back 无参数。"
    "坐标为截图像素坐标。输出格式严格为两行：\nThought: <简短动作意图>\nAction: <动作 JSON>"
)


def compact_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def action_summary(step):
    """给历史摘要用的一句话动作描述。"""
    at = step.get("action", "?")
    g = step.get("grounding") or {}
    name = step.get("action_target") or g.get("element_name")
    if at in ("CLICK", "click") and name:
        return f"点击「{name}」"
    if at in ("LEFT_DOUBLE", "RIGHT_SINGLE") and name:
        return f"{at} 「{name}」"
    try:
        aj = json.loads(step.get("action_json", "{}"))
        p = aj.get("parameters", {})
    except Exception:
        p = {}
    if at == "TYPE":
        return f"输入「{p.get('text', '')}」"
    if at == "HOTKEY":
        return f"快捷键 {'+'.join(p.get('keys', []))}"
    if at == "SCROLL":
        return f"滚动({p.get('direction', '')})"
    return at


def build_history(steps, upto):
    """前 upto 步的动作摘要 (压缩)。"""
    if upto == 0:
        return "（这是第一步）"
    lines = []
    for i in range(upto):
        lines.append(f"{i + 1}. {action_summary(steps[i])}")
    return "\n".join(lines)


def page_context(step):
    g = step.get("graph") or {}
    ann = step.get("annotation") or {}
    bits = []
    # arrived/context node 不直接喂给模型 (训练时模型看不到图)，这里只用页面名
    analysis = ann.get("analysis")
    if analysis:
        # analysis 是英文像素级描述，对训练无益，跳过
        pass
    return ""


def keep_step(step, keep_types, require_effect, include_impossible):
    ann = step.get("annotation") or {}
    st = ann.get("step_type")
    eff = ann.get("had_effect")
    at = step.get("action")
    if at in TERMINAL_ACTIONS:
        return True
    if at == "IMPOSSIBLE":
        return include_impossible
    if st not in keep_types:
        return False
    if require_effect and eff is False:
        return False
    return True


def visual_steps(meta, steps):
    """Read verified visual records without rewriting their source evidence."""
    if (meta.get("scenario_success") is not True or meta.get("errors")
            or (meta.get("final_verification") or {}).get("complete") is not True):
        return None
    result = []
    for step in steps:
        primitives = (step.get("grounding") or {}).get("primitive_actions") or []
        frames = step.get("frames") or {}
        if (step.get("committed") is not True
                or (step.get("verification") or {}).get("outcome") != "success"
                or len(primitives) != 1 or not frames.get("before") or not frames.get("after")):
            return None
        primitive = primitives[0]
        mobile = primitive.get("action_type") in ANDROID_ACTIONS
        if not primitive.get("action_type") or (not mobile and not isinstance(primitive.get("parameters"), dict)):
            return None
        spec = step.get("action_spec") or {}
        result.append({"frame": frames["before"], "action": primitive["action_type"],
                       "action_json": compact_json(primitive),
                       "action_target": spec.get("target") or "",
                       "system_prompt": ANDROID_SYSTEM_PROMPT if mobile else SYSTEM_PROMPT,
                       # This is the submitted action intent, never its after-frame verdict.
                       "thinking": spec.get("purpose") or spec.get("target") or ""})
    return result


def make_sample(episode_meta, steps, idx, frame_path, with_history):
    step = steps[idx]
    instruction = (episode_meta.get("instruction") or "").strip()
    thinking = (step.get("thinking") or "").strip()
    try:
        aj = json.loads(step.get("action_json", "{}"))
    except Exception:
        aj = {"action_type": step.get("action", "WAIT"), "parameters": {}}
    action_str = compact_json(aj)

    user_parts = ["<image>"]
    user_parts.append(f"任务: {instruction}")
    if with_history:
        user_parts.append("已完成的操作:\n" + build_history(steps, idx))
    user_parts.append("请输出下一步。")
    user_content = "\n\n".join(user_parts)

    assistant_content = f"Thought: {thinking}\nAction: {action_str}"

    return {
        "messages": [
            {"role": "system", "content": step.get("system_prompt", SYSTEM_PROMPT)},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        "images": [frame_path],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", default="collections/OS",
                    help="采集根目录 (含 */setting/episodes/*/)")
    ap.add_argument("--out", default="data/sft", help="输出目录")
    ap.add_argument("--val_ratio", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--keep_types", default=",".join(sorted(DEFAULT_KEEP_TYPES)),
                    help="保留的 step_type, 逗号分隔; 传 'ALL' 不按类型过滤")
    ap.add_argument("--no_require_effect", action="store_true",
                    help="不要求 had_effect=True (默认要求)")
    ap.add_argument("--include_impossible", action="store_true",
                    help="保留 IMPOSSIBLE 步作为拒答样本")
    ap.add_argument("--no_history", action="store_true",
                    help="user turn 不放历史动作摘要")
    ap.add_argument("--image_root_replace", default="",
                    help="形如 '本地前缀::训练机前缀', 重写图片绝对路径")
    args = ap.parse_args()

    keep_types = None if args.keep_types.strip().upper() == "ALL" \
        else set(t.strip() for t in args.keep_types.split(",") if t.strip())
    require_effect = not args.no_require_effect

    src_repl = None
    if args.image_root_replace:
        a, b = args.image_root_replace.split("::", 1)
        src_repl = (a, b)

    traj_files = sorted(glob.glob(
        os.path.join(args.collections, "*", "*", "episodes", "*", "trajectory.json")))
    # 兼容 collections/OS/<batch>/setting/episodes/*  和  collections/android/...
    if not traj_files:
        traj_files = sorted(glob.glob(
            os.path.join(args.collections, "**", "trajectory.json"), recursive=True))

    samples = []
    stats = {"episodes": 0, "steps_total": 0, "steps_kept": 0,
             "dropped_no_frame": 0, "dropped_no_thinking": 0, "by_action": {},
             "visual_episodes": 0, "dropped_visual_episodes": 0}

    for tf in traj_files:
        d = json.load(io.open(tf, encoding="utf-8"))
        meta = d.get("meta", {})
        steps = d.get("steps", [])
        ep_dir = os.path.dirname(tf)
        stats["episodes"] += 1
        stats["steps_total"] += len(steps)
        visual = meta.get("schema_version") == "m13.visual_collection.v1"
        if visual:
            stats["visual_episodes"] += 1
            steps = visual_steps(meta, steps)
            if steps is None:
                stats["dropped_visual_episodes"] += 1
                continue
        for idx, step in enumerate(steps):
            if not visual and keep_types is not None and not keep_step(
                    step, keep_types, require_effect, args.include_impossible):
                continue
            frame = step.get("frame")
            if not frame:
                stats["dropped_no_frame"] += 1
                continue
            fp = os.path.join(ep_dir, "screenshots", frame)
            if not os.path.exists(fp):
                # 有的批次截图直接在 ep_dir 下
                alt = os.path.join(ep_dir, frame)
                if os.path.exists(alt):
                    fp = alt
                else:
                    stats["dropped_no_frame"] += 1
                    continue
            if not (step.get("thinking") or "").strip():
                stats["dropped_no_thinking"] += 1
                continue
            fp_abs = os.path.abspath(fp)
            if src_repl:
                fp_abs = fp_abs.replace(src_repl[0], src_repl[1])
                # 跨系统: Windows 反斜杠 -> Linux 正斜杠 (仅在重写到训练机路径时)
                fp_abs = fp_abs.replace("\\", "/")
            s = make_sample(meta, steps, idx, fp_abs, not args.no_history)
            samples.append(s)
            stats["steps_kept"] += 1
            a = step.get("action", "?")
            stats["by_action"][a] = stats["by_action"].get(a, 0) + 1

    random.Random(args.seed).shuffle(samples)
    n_val = int(len(samples) * args.val_ratio)
    val, train = samples[:n_val], samples[n_val:]

    os.makedirs(args.out, exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        with io.open(os.path.join(args.out, name + ".jsonl"), "w", encoding="utf-8") as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["train"] = len(train)
    stats["val"] = len(val)
    with io.open(os.path.join(args.out, "stats.json"), "w", encoding="utf-8") as fo:
        json.dump(stats, fo, ensure_ascii=False, indent=2)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\n[done] train={len(train)} val={len(val)} -> {args.out}/")


if __name__ == "__main__":
    main()
