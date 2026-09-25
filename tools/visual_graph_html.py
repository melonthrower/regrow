"""Standalone HTML viewer for a visual-traversal graph (networkx node-link).

Lays nodes out by BFS depth from the root (root on top, deeper pages lower) so
you can SEE how far exploration reached and where the graph stays shallow.
Each node is its screenshot thumbnail; directed edges are drawn as SVG arrows;
clicking a node enlarges it. Self-contained (screenshots embedded as base64).

Usage:
  python tools/visual_graph_html.py <run_dir_with_graph.json> -o out.html
"""
from __future__ import annotations
import argparse, base64, json, os
from collections import deque
from pathlib import Path


def _find_shot(run_dir: Path, node_id: str) -> Path | None:
    for c in (run_dir / "screenshots" / f"{node_id}.png",
              run_dir / "node_artifacts" / node_id / "screenshot.png"):
        if c.exists():
            return c
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path, help="run dir containing graph.json")
    ap.add_argument("-o", "--output", type=Path, default=Path("_visual_graph.html"))
    args = ap.parse_args()

    gpath = args.path / "graph.json"
    if not gpath.exists():
        f = list(args.path.rglob("graph.json"))
        gpath = f[0] if f else gpath
    run_dir = gpath.parent
    data = json.loads(gpath.read_text(encoding="utf-8"))

    nodes = data.get("nodes", [])
    edges = data.get("edges", data.get("links", []))
    ids = [n.get("id") for n in nodes]
    ninfo = {n.get("id"): n for n in nodes}
    adj: dict = {i: [] for i in ids}
    ein: dict = {i: 0 for i in ids}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adj and t in adj:
            adj[s].append((t, e.get("element_label") or e.get("semantic_description") or ""))
            ein[t] = ein.get(t, 0) + 1

    # root = an in-degree-0 node (or first); BFS depth layout
    roots = [i for i in ids if ein.get(i, 0) == 0] or (ids[:1])
    depth = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        u = q.popleft()
        for (v, _l) in adj.get(u, []):
            if v not in depth:
                depth[v] = depth[u] + 1
                q.append(v)
    for i in ids:                      # disconnected/orphan nodes
        depth.setdefault(i, max(depth.values(), default=0) + 1)

    layers: dict = {}
    for i in ids:
        layers.setdefault(depth[i], []).append(i)

    # positions
    COLW, ROWH, TW = 230, 300, 200
    pos = {}
    width = max((len(v) for v in layers.values()), default=1) * COLW + 80
    for d in sorted(layers):
        row = layers[d]
        x0 = (width - len(row) * COLW) // 2
        for k, i in enumerate(row):
            pos[i] = (x0 + k * COLW + 40, d * ROWH + 40)
    height = (max(layers) + 1) * ROWH + 80

    def b64(i):
        p = _find_shot(run_dir, i)
        if not p:
            return ""
        return base64.b64encode(p.read_bytes()).decode()

    # build svg edges
    seg = []
    for u in ids:
        ux, uy = pos[u]
        for (v, lbl) in adj.get(u, []):
            vx, vy = pos[v]
            seg.append(f'<line x1="{ux+TW//2}" y1="{uy+150}" x2="{vx+TW//2}" y2="{vy}" '
                       f'stroke="#88a" stroke-width="1.5" marker-end="url(#a)"/>')
    cards = []
    for i in ids:
        x, y = pos[i]
        img = b64(i)
        ncl = ninfo[i].get("num_clickable", ninfo[i].get("clickable", ""))
        lbl = f"d{depth[i]} · {i[:8]}"
        out_n = len(adj.get(i, []))
        src = f'data:image/png;base64,{img}' if img else ''
        cards.append(
            f'<div class="nd" style="left:{x}px;top:{y}px" onclick="big(\'{src}\')">'
            f'<img src="{src}"/><div class="cap">{lbl} →{out_n}</div></div>')

    html = f"""<!doctype html><meta charset=utf-8><title>visual graph</title>
<style>body{{margin:0;background:#111;font:12px monospace;color:#ccc}}
#wrap{{position:relative;width:{width}px;height:{height}px}}
.nd{{position:absolute;width:{TW}px;cursor:pointer}}
.nd img{{width:{TW}px;border:2px solid #557;border-radius:4px;display:block}}
.nd:hover img{{border-color:#fc6}}
.cap{{text-align:center;color:#9ab;padding:2px}}
svg{{position:absolute;left:0;top:0;pointer-events:none}}
#ov{{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;align-items:center;justify-content:center;z-index:9}}
#ov img{{max-height:96vh;max-width:96vw}}
#hd{{position:fixed;top:0;left:0;right:0;background:#222;padding:6px 12px;z-index:5}}</style>
<div id=hd>visual graph — {len(ids)} nodes, {len(edges)} edges · depth 0..{max(layers)} · app {data.get('app_name','')}</div>
<div id=wrap style="margin-top:30px">
<svg width={width} height={height}><defs><marker id=a markerWidth=8 markerHeight=8 refX=6 refY=3 orient=auto>
<path d="M0,0 L6,3 L0,6" fill="#88a"/></marker></defs>{''.join(seg)}</svg>
{''.join(cards)}</div>
<div id=ov onclick="this.style.display='none'"><img id=ovi></div>
<script>function big(s){{if(!s)return;document.getElementById('ovi').src=s;document.getElementById('ov').style.display='flex';}}</script>"""
    args.output.write_text(html, encoding="utf-8")
    print(f"wrote {args.output} — {len(ids)} nodes, {len(edges)} edges, "
          f"depth 0..{max(layers)}, layers={ {d:len(v) for d,v in sorted(layers.items())} }")


if __name__ == "__main__":
    main()
