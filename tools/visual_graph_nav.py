"""Navigable, scroll-aware HTML viewer for a visual-traversal graph.

Fixes the "clicks land on blank" confusion WITHOUT re-traversal, using the
existing data (each element carries ``scroll_steps``):

  * TOP strip: thumbnails of ALL nodes (depth-ordered) — click any to inspect it,
    so the whole graph is visible, not just what's reachable by clicking.
  * LEFT: the selected node's (top-frame) screenshot, with red dots ONLY on the
    edges whose source element is on the top frame (scroll_steps==0) — those
    coords match the image. Below-the-fold edges are NOT drawn (they'd land on
    blank top-frame space); they appear in the right list tagged "↓N".
  * RIGHT: every outgoing edge as a button (target thumbnail + label); click to
    jump to that target. Starts on the real home (max out-degree), not a sparse
    pre-home node.
  * Edges to the SAME target are de-duplicated (prefer a clean title over a
    "... icon" / subtitle fragment).

Usage:  python tools/visual_graph_nav.py <run_dir_with_graph.json> -o out.html
"""
from __future__ import annotations
import argparse, base64, json
from collections import Counter, deque
from pathlib import Path


def _shot(run_dir: Path, nid: str):
    for c in (run_dir / "node_artifacts" / nid / "screenshot.png",
              run_dir / "screenshots" / f"{nid}.png"):
        if c.exists():
            return c
    return None


def _elements(run_dir: Path, nid: str):
    p = run_dir / "node_artifacts" / nid / "elements.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _nearest_scroll(els, x, y):
    best, bd = 0, 1e18
    for e in els:
        c = e.get("center") or [0, 0]
        d = (c[0] - x) ** 2 + (c[1] - y) ** 2
        if d < bd:
            bd, best = d, int(e.get("scroll_steps", 0) or 0)
    return best


def _is_fragment(lbl: str) -> bool:
    low = (lbl or "").lower()
    return low.endswith("icon") or ("," in (lbl or ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("_visual_nav.html"))
    args = ap.parse_args()

    gpath = args.path / "graph.json"
    if not gpath.exists():
        f = list(args.path.rglob("graph.json"))
        gpath = f[0] if f else gpath
    run_dir = gpath.parent
    data = json.loads(gpath.read_text(encoding="utf-8"))
    nodes = [n.get("id") for n in data.get("nodes", [])]
    edges = data.get("edges", data.get("links", []))
    els_cache = {i: _elements(run_dir, i) for i in nodes}

    out: dict = {i: {} for i in nodes}     # node -> {target: edge}
    indeg = Counter(); outdeg = Counter()
    adj = {i: [] for i in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s not in out or t is None or t not in out:
            continue
        a = e.get("action", {})
        p = a.get("parameters", a) if isinstance(a, dict) else {}
        x, y = p.get("x"), p.get("y")
        lbl = (e.get("element_label") or e.get("semantic_description") or "").strip()
        ss = _nearest_scroll(els_cache.get(s, []), x or 0, y or 0)
        cand = {"target": t, "label": lbl, "x": x, "y": y, "scroll": ss}
        prev = out[s].get(t)
        if prev is None or (_is_fragment(prev["label"]) and not _is_fragment(lbl)):
            out[s][t] = cand
        adj[s].append(t); outdeg[s] += 1; indeg[t] += 1

    # depth (BFS from in-degree-0 roots) for ordering the overview strip
    roots = [i for i in nodes if indeg[i] == 0] or nodes[:1]
    depth = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in depth:
                depth[v] = depth[u] + 1; q.append(v)
    for i in nodes:
        depth.setdefault(i, 99)
    order = sorted(nodes, key=lambda i: (depth[i], -outdeg[i]))
    start = outdeg.most_common(1)[0][0] if outdeg else (nodes[0] if nodes else "")

    def b64(i):
        p = _shot(run_dir, i)
        return base64.b64encode(p.read_bytes()).decode() if p else ""

    from PIL import Image
    def size(i):
        p = _shot(run_dir, i)
        if not p:
            return [1080, 1920]
        try:
            with Image.open(p) as im:
                return list(im.size)
        except Exception:
            return [1080, 1920]

    model = {
        "order": order, "start": start, "app": data.get("app_name", ""),
        "tot": len(nodes), "edges": len(edges),
        "nodes": {i: {"shot": b64(i), "size": size(i), "depth": depth[i],
                      "out": sorted(out[i].values(), key=lambda e: (e["scroll"], (e["y"] or 0)))}
                  for i in nodes},
    }
    js = json.dumps(model, ensure_ascii=False)

    html = r"""<!doctype html><meta charset=utf-8><title>visual graph nav</title><style>
body{margin:0;background:#0d0d0f;color:#ddd;font:13px system-ui}
#strip{display:flex;gap:6px;overflow-x:auto;padding:8px;background:#16171b;border-bottom:1px solid #222;white-space:nowrap}
#strip .t{flex:0 0 auto;width:60px;cursor:pointer;text-align:center;opacity:.7}
#strip .t.sel{opacity:1}
#strip .t img{width:60px;height:106px;object-fit:cover;border:2px solid #333;border-radius:4px}
#strip .t.sel img{border-color:#fc6}
#strip .t div{font-size:9px;color:#789}
#main{display:flex;height:calc(100vh - 132px)}
#left{flex:0 0 auto;padding:10px;overflow:auto}
#wrap{position:relative;display:inline-block}
#wrap img{max-height:84vh;border:1px solid #333;border-radius:6px;display:block}
.dot{position:absolute;width:3.2%;aspect-ratio:1;margin:-1.6% 0 0 -1.6%;border:2px solid #f33;border-radius:50%;background:rgba(255,50,50,.3)}
#right{flex:1;padding:12px 16px;overflow:auto;border-left:1px solid #222;min-width:340px}
h2{font-size:15px;margin:2px 0 8px;color:#9cf}.meta{color:#789;margin-bottom:8px}
.hint{color:#677;font-size:11px;margin:6px 0 12px}
.eb{display:flex;align-items:center;gap:8px;background:#1a1c22;border:1px solid #2a2d36;border-radius:8px;padding:7px 10px;margin:5px 0;cursor:pointer}
.eb:hover{border-color:#fc6;background:#23262e}
.eb img{width:46px;height:82px;object-fit:cover;border-radius:4px;border:1px solid #333;flex:0 0 auto}
.eb .nm{flex:1}.tg{color:#fa6;font-size:11px}.bk{background:#2a3550;border:0;color:#cde;padding:5px 11px;border-radius:7px;cursor:pointer}
</style>
<div id=strip></div>
<div id=main>
 <div id=left><div id=wrap><img id=shot><div id=dots></div></div></div>
 <div id=right>
   <button class=bk onclick="back()">&larr; 返回</button>
   <h2 id=title></h2><div class=meta id=meta></div>
   <div class=hint>顶部=全部节点(按深度排,点缩略图看任意节点)。左图红圈=本页顶屏可点跳转(坐标已对齐)。右侧=全部出边,点跳转;「↓N」表示该入口要下滑 N 屏才可见(故未画到顶图)。</div>
   <div id=elist></div>
 </div>
</div>
<script>
const M=DATA,N=M.nodes;let cur=M.start,hist=[];
function strip(){const s=document.getElementById('strip');s.innerHTML='';
 M.order.forEach(id=>{const n=N[id];const t=document.createElement('div');t.className='t'+(id===cur?' sel':'');t.onclick=()=>{if(id!==cur){hist.push(cur);cur=id;render();}};
  t.innerHTML='<img src="data:image/png;base64,'+n.shot+'"><div>d'+n.depth+' '+id.slice(0,4)+'<br>→'+n.out.length+'</div>';s.appendChild(t);});}
function render(){const n=N[cur];if(!n)return;
 document.getElementById('shot').src='data:image/png;base64,'+n.shot;
 document.getElementById('title').textContent=cur.slice(0,12)+'  · 深度'+n.depth+' · '+n.out.length+' 出边';
 document.getElementById('meta').textContent='app '+M.app+' · 共 '+M.tot+' 节点 / '+M.edges+' 边';
 const dots=document.getElementById('dots');dots.innerHTML='';
 n.out.forEach(e=>{if(e.scroll===0&&e.x!=null){const dv=document.createElement('div');dv.className='dot';
   dv.style.left=(e.x/n.size[0]*100)+'%';dv.style.top=(e.y/n.size[1]*100)+'%';dots.appendChild(dv);}});
 const el=document.getElementById('elist');el.innerHTML='';
 n.out.forEach((e,i)=>{const tg=N[e.target];const d=document.createElement('div');d.className='eb';
  d.onclick=()=>{if(N[e.target]){hist.push(cur);cur=e.target;render();}};
  const th=tg&&tg.shot?'<img src="data:image/png;base64,'+tg.shot+'">':'';
  const tag=e.scroll>0?' <span class=tg>↓'+e.scroll+'</span>':' <span style="color:#5a5">●顶屏</span>';
  d.innerHTML=th+'<div class=nm>'+(i+1)+'. '+(e.label||'(按钮)')+tag+'<br><span style="color:#678">→ '+e.target.slice(0,8)+' (d'+(tg?tg.depth:'?')+')</span></div>';el.appendChild(d);});
 strip();
 const sel=document.querySelector('#strip .t.sel');if(sel)sel.scrollIntoView({inline:'center',block:'nearest'});}
function back(){if(hist.length){cur=hist.pop();render();}}
render();
</script>"""
    html = html.replace("DATA", js)
    args.output.write_text(html, encoding="utf-8")
    nde = sum(len(v) for v in out.values())
    print(f"wrote {args.output} — {len(nodes)} nodes, {nde} edges, start(home)={start[:8]}")


if __name__ == "__main__":
    main()
