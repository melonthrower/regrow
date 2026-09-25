"""离线图增强:基于 uid_transition_map 补 inferred 边,让任意页→任意页可达。

根因(见 design_decisions D27):遍历只在主页系统点了侧栏所有项,子页(Sound等)只探页内
控件,没建侧栏横向边 → 子页之间"无路径"。但 GNOME Settings 每页侧栏都列着所有页,任意页
可点任意页。本脚本用已学到的 uid→目标 转移,为每个含该侧栏项(同 global_uid)的节点补一条
inferred 边,补全跨页可达性。

inferred 边下游全部支持:导航(scenario_executor._graph_navigate 按 element_label name 在
实机匹配)、heal(graph_supplement 执行成功自动升级 executed)、completion 统计、save/load。

用法:
  python tools/augment_inferred_edges.py --graph <0_graph.json>           # 原地增强(存.bak)
  python tools/augment_inferred_edges.py --graph <..> --out <new.json>    # 写新文件
  python tools/augment_inferred_edges.py --glob "result_*/gen_data/*/graphs/0_graph.json"  # 批量
  加 --dry-run 只报告不写。
"""
import sys, os, glob, json, argparse, shutil
sys.path.insert(0, ".")
sys.path.insert(0, "gui_rewalk")
import networkx as nx
from gui_rewalk.src.core.graph.state_graph import StateGraph


def _edge_kind(action):
    """executed / inferred / other —— 同 completion.classify_edge。"""
    if isinstance(action, list) and action:
        return "executed"
    if isinstance(action, dict):
        if action.get("type") == "inferred":
            return "inferred"
        if action.get("action_type") or action.get("type"):
            return "executed"
    return "other"


def build_uid_transition_map(G):
    """从 EXECUTED 边重建 uid → (dst, label)。只学实际点击的边,不传播 inferred。"""
    uid2dst = {}
    for src, dst, ed in G.edges(data=True):
        if src == dst:
            continue
        if _edge_kind(ed.get("action", {})) != "executed":
            continue
        eid = ed.get("element_id", "")
        label = ed.get("element_label", "")
        if not eid:
            continue
        for elem in G.nodes.get(src, {}).get("elements", []) or []:
            if elem.get("id") == eid:
                uid = elem.get("global_uid", "")
                if uid:
                    # 首次记录优先(主页的侧栏项最规范)
                    uid2dst.setdefault(uid, (dst, label))
                break
    return uid2dst


def augment(sg, verbose=True):
    """给图补 inferred 边。返回 (补边数, 报告dict)。"""
    G = sg.graph
    uid2dst = build_uid_transition_map(G)
    before_edges = G.number_of_edges()
    before_wcc = nx.number_weakly_connected_components(G)

    added = 0
    samples = []
    for n in list(G.nodes()):
        for elem in G.nodes[n].get("elements", []) or []:
            uid = elem.get("global_uid", "")
            if not uid or uid not in uid2dst:
                continue
            dst, label = uid2dst[uid]
            if dst == n or dst not in G:
                continue
            if G.has_edge(n, dst):
                continue
            # 接地名必须可提取且最好是实机真实 a11y name(导航按 name 在实机匹配)。
            # 优先 elem.name(真实a11y名,如"Primary Menu"),其次 label 冒号后,
            # 最后 vlm_semantic_name(描述性,实机可能匹配不中→由VLM兜底)。
            real_name = elem.get("name", "") or ""
            label_name = label.split(":", 1)[1].strip() if ":" in (label or "") else ""
            name = real_name or label_name or elem.get("vlm_semantic_name", "")
            if not name:
                continue
            tag = elem.get("tag", "") or elem.get("role", "")
            # 用真实 name 重建 label, 保证 _edge_target_name 提取后实机能匹配
            edge_label = f"Click {tag}: {name}" if real_name else (label or f"Click {tag}: {name}")
            G.add_edge(n, dst, **{
                "action": {"type": "inferred"},
                "element_id": elem.get("id", ""),
                "element_label": edge_label,
                "semantic_description": "inferred persistent-nav (sidebar) transition",
                "inferred_via_uid": uid,
            })
            added += 1
            if len(samples) < 8:
                samples.append((n[:8], dst[:8], name))

    after_wcc = nx.number_weakly_connected_components(G)
    report = {
        "learned_transitions": len(uid2dst),
        "edges_before": before_edges,
        "edges_after": G.number_of_edges(),
        "inferred_added": added,
        "wcc_before": before_wcc,
        "wcc_after": after_wcc,
        "samples": samples,
    }
    if verbose:
        print(f"  学到转移={len(uid2dst)} 补inferred边={added} "
              f"边{before_edges}->{G.number_of_edges()} 连通分量{before_wcc}->{after_wcc}")
        for s, d, nm in samples:
            print(f"    {s} → {d}  via 点击 [{nm}]")
    return added, report


def process_one(path, out=None, backup=True, dry=False):
    sg = StateGraph.load(path)
    print(f"[{path}] nodes={sg.graph.number_of_nodes()}")
    added, report = augment(sg)
    if dry:
        print("  (dry-run, 不写)")
        return report
    if added == 0:
        print("  无新边可补,跳过写")
        return report
    target = out or path
    if backup and target == path and not os.path.exists(path + ".bak"):
        shutil.copy(path, path + ".bak")
    sg.save(target)
    print(f"  已写 {target}")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="")
    ap.add_argument("--glob", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paths = []
    if args.graph:
        paths = [args.graph]
    elif args.glob:
        paths = sorted(glob.glob(args.glob))
    else:
        print("需 --graph 或 --glob")
        return 1
    if not paths:
        print("无匹配图文件")
        return 1

    total = 0
    for p in paths:
        try:
            r = process_one(p, out=args.out or None,
                            backup=not args.no_backup, dry=args.dry_run)
            total += r.get("inferred_added", 0)
        except Exception as e:
            print(f"[{p}] 失败: {e}")
    print(f"=== 共补 {total} 条 inferred 边,处理 {len(paths)} 个图 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
