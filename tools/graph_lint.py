#!/usr/bin/env python3
"""[2026-07-08 用户] Graph quality linter — 冒烟测试/质检一张 graph.json。

四条不变式(用户定义):
  1. 每个按钮只属于一个区块(region 唯一且非空)
  2. 没有不可达的节点(从根 BFS 全覆盖)
  3. 所有节点和按钮都被探索过(nav 候选 visited=true)
  4. visited 的按钮都有出边(点过就该留下 transition)

结合 stop_reason:只有 frontier_empty(探完)时 #3/#4 的未覆盖才算 BUG;
max_actions/max_states/thrash 等截断时未覆盖是预期,降级为 INFO。

退出码:0=PASS(无 ERROR),1=FAIL(有 ERROR),2=用法错误。
用法:python tools/graph_lint.py <graph.json> [--json] [--strict]
"""
from __future__ import annotations
import json, sys, collections
from typing import Any, Dict, List


_DATA_CONTROL_TYPES = {
    "input", "textbox", "text field", "text_field", "checkbox", "radio",
    "radio button", "switch", "toggle", "slider", "combobox", "combo box",
    "select", "dropdown",
}


def _load(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _nodes(d): return d.get("nodes", []) or d.get("states", [])
def _sid(nd): return nd.get("state_id") or nd.get("id")


def _root(d) -> "str | None":
    ns = _nodes(d)
    for nd in ns:
        if not (nd.get("action_path_from_root") or []):
            return _sid(nd)
    return _sid(ns[0]) if ns else None


def _is_nav(e: Dict[str, Any]) -> bool:
    """A navigation-worth button that SHOULD be explored — mirrors the engine's
    ledger filter: category=navigation, has a real name, not a back/chrome key."""
    if (e.get("category") or "").lower() != "navigation":
        return False
    if e.get("back"):
        return False
    if " ".join((e.get("el_type") or "").lower().split()) in _DATA_CONTROL_TYPES:
        return False
    return bool((e.get("name") or "").strip())


def check_run_status(d) -> List[Dict[str, Any]]:
    """A budget stop is a valid artifact, but never a complete/gold graph."""
    stop = d.get("stop_reason", "incomplete")
    if stop == "frontier_empty":
        return []
    return [{"sev": "WARN", "code": "incomplete_run",
             "msg": f"stop_reason={stop}; frontier 未自然耗尽"}]


def check_runtime_unreachable_flags(d) -> List[Dict[str, Any]]:
    """Nodes the router itself proved unreachable are not safely replayable."""
    return [
        {"sev": "WARN", "code": "flagged_unreachable", "node": _sid(nd),
         "msg": f"节点 {str(_sid(nd))[:8]} 被运行时标记 unreachable"}
        for nd in _nodes(d) if nd.get("unreachable")
    ]


def check_edge_quality(d) -> List[Dict[str, Any]]:
    """Production click guards: semantic landing, region binding, self-loop waste."""
    out: List[Dict[str, Any]] = []
    nodes = {_sid(nd): nd for nd in _nodes(d)}
    edges = d.get("edges", []) or d.get("links", [])
    unverified_nav = missing_region = 0
    self_loops = 0
    for ed in edges:
        if ed.get("source") == ed.get("target"):
            self_loops += 1
        verdict = (ed.get("effect_verdict") or "").strip()
        if verdict in ("no_effect", "transitioned_inconsistent"):
            out.append({"sev": "ERROR", "code": "bad_click_effect",
                        "node": ed.get("source"),
                        "msg": f"边「{ed.get('element_label')}」效果={verdict}"})
        label = str(ed.get("element_label") or "")
        if "\ufffd" in label or "����" in label:
            out.append({"sev": "WARN", "code": "garbled_edge_label",
                        "node": ed.get("source"), "msg": f"乱码边标签: {label!r}"})

        src = nodes.get(ed.get("source"), {})
        eid = str(ed.get("element_id", ""))
        low = label.strip().lower()
        matched = [e for e in src.get("elements", [])
                   if str(e.get("id", "")) == eid
                   or (e.get("name") or "").strip().lower() == low]
        nav_edge = any(_is_nav(e) for e in matched)
        if not nav_edge:
            continue
        if not (ed.get("region") or "").strip():
            missing_region += 1
        if ed.get("landing_verified") is not True:
            unverified_nav += 1

    if missing_region:
        out.append({"sev": "WARN", "code": "nav_edges_missing_region",
                    "msg": f"{missing_region} 条导航边没有 region，无法可靠继承/路由"})
    if unverified_nav:
        out.append({"sev": "WARN", "code": "unverified_navigation_edges",
                    "msg": f"{unverified_nav} 条导航边没有语义落地验收"})
    if edges and self_loops / len(edges) > 0.10:
        out.append({"sev": "WARN", "code": "self_loop_rate",
                    "msg": f"自环 {self_loops}/{len(edges)}="
                           f"{self_loops / len(edges):.1%}，疑似重复/死点过多"})
    return out


def check_reachable(d) -> List[Dict[str, Any]]:
    """#2 无不可达节点: 从根 BFS,任何到不了的节点 = ERROR(注册了却没入边)。"""
    ns = _nodes(d)
    root = _root(d)
    if not root:
        return [{"sev": "ERROR", "code": "no_root", "msg": "图里找不到根节点"}]
    adj = collections.defaultdict(list)
    for ed in d.get("edges", []) or d.get("links", []):
        adj[ed.get("source")].append(ed.get("target"))
    seen, stack = set(), [root]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj.get(n, []))
    out = []
    for nd in ns:
        sid = _sid(nd)
        if sid not in seen:
            out.append({"sev": "ERROR", "code": "unreachable",
                        "node": sid, "msg": f"节点 {str(sid)[:8]} 从根不可达"})
    return out


def check_region_unique(d) -> List[Dict[str, Any]]:
    """#1 每个按钮只属于一个区块: 同一 uid 在一个节点里出现多条 region = 冲突;
    region 为空(单区块页面除外)= 未分配,记 INFO。"""
    out = []
    for nd in _nodes(d):
        sid = _sid(nd)
        by_uid = collections.defaultdict(set)
        for e in nd.get("elements", []):
            if _is_nav(e):
                by_uid[e.get("uid")].add((e.get("region") or "").strip())
        for uid, regs in by_uid.items():
            nonblank = {r for r in regs if r}
            if len(nonblank) > 1:
                out.append({"sev": "ERROR", "code": "region_conflict",
                            "node": sid, "msg": f"按钮 {uid} 属于多个区块 {sorted(nonblank)}"})
    return out


def check_coverage(d, complete: bool) -> List[Dict[str, Any]]:
    """#3 所有 nav 按钮 visited=true;#4 visited 的按钮都有出边。
    complete=True(stop_reason=frontier_empty)时未覆盖=ERROR,否则=INFO(截断,预期)。"""
    sev_uncov = "ERROR" if complete else "INFO"
    out = []
    out_uids = collections.defaultdict(set)   # node -> {clicked element_id/label}
    for ed in d.get("edges", []) or d.get("links", []):
        out_uids[ed.get("source")].add(str(ed.get("element_id", "")))
        out_uids[ed.get("source")].add((ed.get("element_label") or "").strip().lower())
    for nd in _nodes(d):
        sid = _sid(nd)
        navs = [e for e in nd.get("elements", []) if _is_nav(e)]
        unvis = [e for e in navs if not e.get("visited")]
        if unvis:
            names = ", ".join((e.get("name") or "?") for e in unvis[:5])
            out.append({"sev": sev_uncov, "code": "unvisited_button", "node": sid,
                        "msg": f"{len(unvis)}/{len(navs)} 个 nav 按钮未探索: {names}"})
        # #4: visited 却没有任何出边匹配(既非自环也非共享,应留下 transition)
        for e in navs:
            if not e.get("visited"):
                continue
            keys = {str(e.get("id", "")), (e.get("name") or "").strip().lower()}
            if not (keys & out_uids.get(sid, set())):
                out.append({"sev": "INFO", "code": "visited_no_edge", "node": sid,
                            "msg": f"按钮「{e.get('name')}」visited 但无出边"
                                   "(可能自环/共享按钮/同类折叠)"})
    return out


def lint(path: str) -> Dict[str, Any]:
    d = _load(path)
    stop = d.get("stop_reason", "incomplete")
    complete = stop == "frontier_empty"
    findings = (check_run_status(d) + check_reachable(d)
                + check_runtime_unreachable_flags(d)
                + check_region_unique(d) + check_edge_quality(d)
                + check_coverage(d, complete))
    by_sev = collections.Counter(f["sev"] for f in findings)
    return {"path": path, "app": d.get("app_name"),
            "nodes": len(_nodes(d)), "edges": len(d.get("edges", []) or d.get("links", [])),
            "stop_reason": stop, "complete_run": complete,
            "errors": by_sev.get("ERROR", 0), "warns": by_sev.get("WARN", 0),
            "infos": by_sev.get("INFO", 0), "findings": findings}


def main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    strict = "--strict" in argv   # strict: WARN/INFO 也算失败
    if len(args) != 1:
        print(__doc__)
        return 2
    r = lint(args[0])
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"[{r['app']}] 节点{r['nodes']} 边{r['edges']} stop={r['stop_reason']}"
              f" -> ERROR {r['errors']} / WARN {r['warns']} / INFO {r['infos']}")
        for f in r["findings"]:
            nd = str(f.get("node", ""))[:8]
            print(f"  {f['sev']:5s} {f['code']:18s} {nd:8s} {f['msg']}")
    bad = r["errors"] + (r["warns"] + r["infos"] if strict else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
