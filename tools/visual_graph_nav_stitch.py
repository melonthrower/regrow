"""Navigable graph viewer with the STITCHED FULL-PAGE image on the left.

LEFT  : the selected node's full-page composite (screenshots/<id>__fullpage.png),
        shown at a fixed width and SCROLLABLE (these images are tall — a whole
        page stitched top->bottom).
RIGHT : every outgoing edge as a clickable button (target thumbnail + label) ->
        click to jump to that target node.
TOP   : all nodes as thumbnails (depth-ordered) -> click any to inspect it.

Falls back to the top-frame screenshot for nodes that fit one viewport (no
composite). Self-contained (images embedded as base64).

Usage:  python tools/visual_graph_nav_stitch.py <run_dir_with_graph.json> -o out.html
"""
from __future__ import annotations
import argparse, base64, json
from collections import Counter, deque
from pathlib import Path


def _full(run_dir: Path, nid: str):
    # prefer the stitched full-page composite; fall back to the node image / top frame
    for c in (run_dir / "screenshots" / f"{nid}__fullpage.png",
              run_dir / "node_artifacts" / nid / "screenshot.png",
              run_dir / "screenshots" / f"{nid}.png"):
        if c.exists():
            return c
    return None


def _is_frag(lbl: str) -> bool:
    low = (lbl or "").lower()
    return low.endswith("icon") or low in ("", "back", "返回")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("_stitch_nav.html"))
    args = ap.parse_args()

    gpath = args.path / "graph.json"
    if not gpath.exists():
        f = list(args.path.rglob("graph.json"))
        gpath = f[0] if f else gpath
    run_dir = gpath.parent
    data = json.loads(gpath.read_text(encoding="utf-8"))
    nodes = [n.get("id") for n in data.get("nodes", [])]
    edges = data.get("edges", data.get("links", []))

    out: dict = {i: {} for i in nodes}
    indeg = Counter(); outdeg = Counter(); adj = {i: [] for i in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s not in out or t is None or t not in out:
            continue
        lbl = (e.get("element_label") or e.get("semantic_description") or "").strip()
        prev = out[s].get(t)
        if prev is None or (_is_frag(prev) and not _is_frag(lbl)):
            out[s][t] = lbl
        adj[s].append(t); outdeg[s] += 1; indeg[t] += 1

    roots = [i for i in nodes if indeg[i] == 0] or nodes[:1]
    depth = {r: 0 for r in roots}; q = deque(roots)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in depth:
                depth[v] = depth[u] + 1; q.append(v)
    for i in nodes:
        depth.setdefault(i, 99)
    order = sorted(nodes, key=lambda i: (depth[i], -outdeg[i]))
    start = outdeg.most_common(1)[0][0] if outdeg else (nodes[0] if nodes else "")

    from PIL import Image
    def b64(i):
        p = _full(run_dir, i)
        return base64.b64encode(p.read_bytes()).decode() if p else ""
    def hw(i):
        p = _full(run_dir, i)
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
        "nodes": {i: {"shot": b64(i), "size": hw(i), "depth": depth[i],
                      "full": (run_dir / "screenshots" / f"{i}__fullpage.png").exists(),
                      "out": [{"target": t, "label": out[i][t]} for t in out[i]]}
                  for i in nodes},
    }
    js = json.dumps(model, ensure_ascii=False)

    html = r"""<!doctype html><meta charset=utf-8><title>stitched graph nav</title><style>
body{margin:0;background:#0d0d0f;color:#ddd;font:13px system-ui}
#strip{display:flex;gap:6px;overflow-x:auto;padding:8px;background:#16171b;border-bottom:1px solid #222;white-space:nowrap}
#strip .t{flex:0 0 auto;width:54px;cursor:pointer;text-align:center;opacity:.65}
#strip .t.sel{opacity:1}
#strip .t img{width:54px;height:96px;object-fit:cover;object-position:top;border:2px solid #333;border-radius:4px}
#strip .t.sel img{border-color:#fc6}
#strip .t div{font-size:9px;color:#789}
#main{display:flex;height:calc(100vh - 132px)}
#left{flex:0 0 auto;width:420px;padding:10px;overflow:hidden;display:flex;flex-direction:column}
#lhead{color:#9cf;font-size:13px;margin-bottom:6px}
#lscroll{overflow-y:auto;border:1px solid #333;border-radius:6px;background:#000}
#lscroll img{width:400px;display:block}
#right{flex:1;padding:12px 16px;overflow:auto;border-left:1px solid #222;min-width:320px}
h2{font-size:15px;margin:2px 0 8px;color:#9cf}.meta{color:#789;margin-bottom:8px}
.hint{color:#677;font-size:11px;margin:6px 0 12px}
.eb{display:flex;align-items:center;gap:8px;background:#1a1c22;border:1px solid #2a2d36;border-radius:8px;padding:7px 10px;margin:5px 0;cursor:pointer}
.eb:hover{border-color:#fc6;background:#23262e}
.eb img{width:42px;height:74px;object-fit:cover;object-position:top;border-radius:4px;border:1px solid #333;flex:0 0 auto}
.eb .nm{flex:1}.tg{color:#fa6;font-size:11px}.bk{background:#2a3550;border:0;color:#cde;padding:5px 11px;border-radius:7px;cursor:pointer;margin-bottom:8px}
.badge{font-size:10px;padding:1px 5px;border-radius:3px;background:#243;color:#7d9;margin-left:6px}
</style>
<div id=strip></div>
<div id=main>
 <div id=left>
   <div id=lhead></div>
   <div id=lscroll><img id=shot></div>
 </div>
 <div id=right>
   <button class=bk onclick="back()">&larr; 返回</button>
   <h2 id=title></h2><div class=meta id=meta></div>
   <div class=hint>左=该节点的整页拼接长图(可上下滚动看完整页)。右=全部出边,点缩略图/标签跳到目标节点。顶部=全部节点。</div>
   <div id=elist></div>
 </div>
</div>
<script>
const M=DATA,N=M.nodes;let cur=M.start,hist=[];
function strip(){const s=document.getElementById('strip');s.innerHTML='';
 M.order.forEach(id=>{const n=N[id];const t=document.createElement('div');t.className='t'+(id===cur?' sel':'');t.onclick=()=>{if(id!==cur){hist.push(cur);cur=id;render();}};
  t.innerHTML='<img src="data:image/png;base64,'+n.shot+'"><div>d'+n.depth+'<br>'+id.slice(0,4)+'</div>';s.appendChild(t);});}
function render(){const n=N[cur];if(!n)return;
 document.getElementById('shot').src='data:image/png;base64,'+n.shot;
 document.getElementById('lscroll').scrollTop=0;
 const tall=(n.size[1]/n.size[0]).toFixed(1);
 document.getElementById('lhead').innerHTML=cur.slice(0,12)+'  '+(n.full?'<span class=badge>整页拼接 '+n.size[0]+'×'+n.size[1]+'</span>':'<span class=badge style="background:#432;color:#da7">单屏</span>');
 document.getElementById('title').textContent=cur.slice(0,12)+'  · 深度'+n.depth+' · '+n.out.length+' 出边';
 document.getElementById('meta').textContent='app '+M.app+' · 共 '+M.tot+' 节点 / '+M.edges+' 边 · 图高'+tall+'屏';
 const el=document.getElementById('elist');el.innerHTML='';
 if(!n.out.length)el.innerHTML='<div class=hint>(无出边:叶子/未展开节点)</div>';
 n.out.forEach((e,i)=>{const tg=N[e.target];const d=document.createElement('div');d.className='eb';
  d.onclick=()=>{if(N[e.target]){hist.push(cur);cur=e.target;render();}};
  const th=tg&&tg.shot?'<img src="data:image/png;base64,'+tg.shot+'">':'';
  d.innerHTML=th+'<div class=nm>'+(i+1)+'. '+(e.label||'(按钮)')+'<br><span style="color:#678">→ '+e.target.slice(0,8)+' (d'+(tg?tg.depth:'?')+')</span></div>';el.appendChild(d);});
 strip();
 const sel=document.querySelector('#strip .t.sel');if(sel)sel.scrollIntoView({inline:'center',block:'nearest'});}
function back(){if(hist.length){cur=hist.pop();render();}}
render();
</script>"""
    html = html.replace("DATA", js)
    args.output.write_text(html, encoding="utf-8")
    nfull = sum(1 for i in nodes if (run_dir / "screenshots" / f"{i}__fullpage.png").exists())
    print(f"wrote {args.output} — {len(nodes)} nodes ({nfull} stitched full-page), "
          f"{len(edges)} edges, start={start[:8]}")


if __name__ == "__main__":
    main()
