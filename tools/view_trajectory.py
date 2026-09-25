"""采集轨迹查看器:看每条采集到的轨迹(任务 + 完成它的步骤序列)在做什么。

数据源:scenario pipeline 产出的 exec_results.json(每条轨迹含 instruction +
trajectory 步骤序列,每步带 前/后截图、动作坐标、思考、子指令、反向判定)。
可选合并同目录 labeled_trajectories.json 的步骤标注(on_path / off_path 等)。

每条轨迹生成一屏,顶部可切换轨迹;每步显示:
  - 操作前截图(红点 + bbox 框出目标元素)→ 操作后截图
  - 这一步要做什么(sub_instruction)、agent 的思考(thinking)
  - 动作类型 + 坐标、点击的元素、反向推理是否判定生效
  - 上一步/下一步,键盘 ← →

用法:
  python tools/view_trajectory.py <exec_results.json 或 含它的目录> [-o out.html]
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_exec(root: Path) -> Path:
    if root.is_file() and root.suffix == ".json":
        return root
    hits = sorted(root.rglob("exec_results.json"))
    if not hits:
        raise FileNotFoundError(f"在 {root} 下找不到 exec_results.json")
    hits.sort(key=lambda p: len(p.parts))
    return hits[0]


def _img_to_data_uri(path: Optional[Path], max_bytes: int = 5_000_000) -> Optional[str]:
    if not path or not path.exists() or path.stat().st_size > max_bytes:
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _resolve(bases: List[Path], rel: str) -> Optional[Path]:
    if not rel:
        return None
    raw = Path(rel.replace("\\", "/"))
    for b in bases:
        for cand in (b / raw, b / raw.name):
            if cand.exists():
                return cand
    return raw if raw.exists() else None


def _parse_action(st: Dict[str, Any]) -> Dict[str, Any]:
    aj = st.get("action_json")
    x = y = None
    text = ""
    atype = st.get("action") or st.get("action_type_hint") or ""
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
    if x is None and isinstance(st.get("element_center"), dict):
        x, y = st["element_center"].get("x"), st["element_center"].get("y")
    return {"type": atype, "x": x, "y": y, "text": text}


def _label_index(coll_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """读取 labeled_trajectories.json,按 scenario_id 索引步骤标注。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    f = coll_dir / "labeled_trajectories.json"
    if not f.exists():
        return out
    try:
        for tr in _load_json(f):
            out[tr.get("scenario_id", "")] = tr.get("steps", [])
    except Exception:
        pass
    return out


def _build_episodes(root: Path) -> Dict[str, Any]:
    """读取 episodes/ 格式。每步只有一张 frame(操作前/当前态),
    用下一步 frame 当"操作后",末步用 final.png。"""
    epdir = root / "episodes" if (root / "episodes").is_dir() else root
    eps = sorted(p for p in epdir.iterdir()
                 if p.is_dir() and (p / "trajectory.json").exists())
    dev_w = dev_h = 0
    out: List[Dict[str, Any]] = []
    for ep in eps:
        tj = _load_json(ep / "trajectory.json")
        meta = tj.get("meta", {}) if isinstance(tj, dict) else {}
        if (ep / "meta.json").exists():
            try:
                meta = {**meta, **_load_json(ep / "meta.json")}
            except Exception:
                pass
        raw = tj.get("steps", []) if isinstance(tj, dict) else tj
        sdir = ep / "screenshots"
        frames = [s.get("frame") for s in raw]
        steps_out: List[Dict[str, Any]] = []
        for k, st in enumerate(raw):
            act = _parse_action(st)
            g = st.get("grounding", {}) or {}
            ann = st.get("annotation", {}) or {}
            before = _resolve([sdir], st.get("frame", ""))
            nxt = frames[k + 1] if k + 1 < len(frames) else "final.png"
            after = _resolve([sdir], nxt)
            if not dev_w and before:
                try:
                    from PIL import Image
                    with Image.open(before) as im:
                        dev_w, dev_h = im.size
                except Exception:
                    pass
            cx = (g.get("element_center") or {}).get("x")
            cy = (g.get("element_center") or {}).get("y")
            # 只有点击类动作才标红点;SCROLL/WAIT/HOTKEY/RIGHT_SINGLE 等无单点坐标
            atype_l = (act["type"] or "").upper()
            is_click = "CLICK" in atype_l or atype_l in ("TAP", "DOUBLE_CLICK", "LEFT_SINGLE")
            if is_click:
                mx = act["x"] if act["x"] is not None else cx
                my = act["y"] if act["y"] is not None else cy
            else:
                mx = my = None
            steps_out.append({
                "i": st.get("step"),
                "type": act["type"],
                "x": mx,
                "y": my,
                "text": act["text"],
                "sub": st.get("instruction", ""),
                "thinking": st.get("thinking", ""),
                "goal": "",
                "elem": g.get("element_name", ""),
                "role": g.get("element_role", ""),
                "bbox": g.get("element_bbox") or {},
                "reverse": ann.get("analysis", ""),
                "had_effect": ann.get("had_effect"),
                "label": ann.get("step_type", ""),
                "evidence": (f"changed_pixels={ann.get('changed_pixels')}, "
                             f"step_completed={ann.get('step_completed')}" if ann else ""),
                "before_img": _img_to_data_uri(before),
                "after_img": _img_to_data_uri(after),
            })
        out.append({
            "id": ep.name,
            "instruction": meta.get("instruction", ""),
            "targets": meta.get("params", {}) or {},
            "success": meta.get("scenario_success"),
            "status": meta.get("final_status", ""),
            "covers": meta.get("covers_pages", []),
            "steps": steps_out,
        })
    return {"source": str(epdir), "dev_w": dev_w or 1920,
            "dev_h": dev_h or 1080, "trajectories": out}


def build(root: Path) -> Dict[str, Any]:
    """自动识别格式:有 episodes/ 或 trajectory.json → episode 格式;否则 exec_results。"""
    if root.is_dir() and (root / "trajectory.json").exists():
        return _build_episodes(root.parent)
    if root.is_dir() and ((root / "episodes").is_dir() or root.name == "episodes"):
        return _build_episodes(root)
    return _build_exec(root)


def _build_exec(root: Path) -> Dict[str, Any]:
    exec_path = _find_exec(root)
    coll_dir = exec_path.parent
    bases = [Path.cwd(), coll_dir, coll_dir.parent, exec_path.parent]
    labels = _label_index(coll_dir)

    scenarios = _load_json(exec_path)
    if isinstance(scenarios, dict):
        scenarios = [scenarios]

    dev_w = dev_h = 0
    out_trajs: List[Dict[str, Any]] = []
    for sc in scenarios:
        sid = sc.get("scenario_id", "?")
        lab = labels.get(sid, [])
        steps_out: List[Dict[str, Any]] = []
        for st in sc.get("trajectory", []):
            act = _parse_action(st)
            before = _resolve(bases, st.get("screen_before", ""))
            after = _resolve(bases, st.get("screen_after", ""))
            if not dev_w and before:
                try:
                    from PIL import Image
                    with Image.open(before) as im:
                        dev_w, dev_h = im.size
                except Exception:
                    pass
            si = st.get("step")
            lrow = next((l for l in lab if l.get("step") in (si, (si or 0) + 1)), {})
            steps_out.append({
                "i": si,
                "type": act["type"], "x": act["x"], "y": act["y"], "text": act["text"],
                "sub": st.get("sub_instruction", ""),
                "thinking": st.get("thinking", ""),
                "goal": st.get("goal", ""),
                "elem": st.get("element_name", ""),
                "role": st.get("element_role", ""),
                "bbox": st.get("element_bbox") or {},
                "reverse": st.get("reverse_analysis", ""),
                "had_effect": st.get("reverse_had_effect"),
                "label": lrow.get("label", ""),
                "evidence": lrow.get("evidence", ""),
                "before_img": _img_to_data_uri(before),
                "after_img": _img_to_data_uri(after),
            })
        out_trajs.append({
            "id": sid,
            "instruction": sc.get("instruction") or sc.get("instruction_en", ""),
            "targets": sc.get("targets", {}),
            "success": sc.get("scenario_success"),
            "status": sc.get("final_status", ""),
            "covers": sc.get("covers_pages", []),
            "steps": steps_out,
        })

    return {"source": str(exec_path), "dev_w": dev_w or 1920,
            "dev_h": dev_h or 1080, "trajectories": out_trajs}


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 14px/1.6 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
  background: #11131a; color: #d7dae0; height: 100vh; overflow: hidden; }
#bar { height: auto; min-height: 56px; display: flex; align-items: center;
  flex-wrap: wrap; gap: 10px 14px; padding: 10px 20px; background: #181b24;
  border-bottom: 1px solid #272d3a; }
#bar h1 { font-size: 15px; font-weight: 600; color: #fff; }
#bar select { background: #232a3a; color: #e3e6ec; border: 1px solid #384156;
  border-radius: 6px; padding: 6px 10px; font-size: 13px; max-width: 640px; }
#bar .spacer { flex: 1; }
#bar button { background: #232a3a; color: #d7dae0; border: 1px solid #384156;
  border-radius: 6px; padding: 7px 15px; font-size: 14px; cursor: pointer; }
#bar button:hover:not(:disabled) { background: #2d3548; }
#bar button:disabled { opacity: .35; cursor: default; }
#counter { font-variant-numeric: tabular-nums; min-width: 84px; text-align: center;
  color: #aeb4c0; font-size: 13px; }
.ok { color: #7ee787; } .fail { color: #ff6b6b; }
#task { padding: 10px 20px; background: #141925; border-bottom: 1px solid #222838;
  font-size: 13px; color: #c6ccd6; }
#task .lbl { color: #6b7180; margin-right: 6px; }
#task .tg { display: inline-block; background: #1f2a38; color: #9fc6ff;
  border-radius: 4px; padding: 1px 8px; margin: 2px 4px 2px 0; font-size: 12px; }
#main { display: flex; height: calc(100vh - 56px); overflow: hidden; }
.shots { flex: 0 1 auto; display: flex; gap: 14px; padding: 18px; align-items: flex-start;
  min-width: 0; }
.shotbox { display: flex; flex-direction: column; align-items: center; gap: 5px; min-width: 0; }
.shotbox .cap { font-size: 12px; color: #8b909c; }
.wrap { position: relative; }
.wrap img { max-height: calc(100vh - 200px); max-width: 30vw; border: 1px solid #272d3a;
  border-radius: 8px; display: block; }
.marker { position: absolute; width: 22px; height: 22px; border: 2px solid #ff4d4f;
  border-radius: 50%; background: #ff4d4f33; transform: translate(-50%,-50%);
  pointer-events: none; box-shadow: 0 0 0 4px #ff4d4f22; }
.bbox { position: absolute; border: 2px solid #ffd866; background: #ffd86618;
  pointer-events: none; }
.arrow { align-self: center; font-size: 26px; color: #4b5366; }
#info { flex: 1 0 340px; padding: 20px 24px; overflow-y: auto; border-left: 1px solid #272d3a;
  background: #141720; min-width: 340px; }
#info .sn { font-size: 13px; color: #6b7180; }
#info .what { font-size: 17px; font-weight: 600; color: #fff; margin: 3px 0 12px; }
.box { border-left: 3px solid #6cb6ff; background: #19202c; padding: 10px 13px;
  border-radius: 0 6px 6px 0; margin: 10px 0; color: #c6ccd6; font-size: 13px; }
.box.think { border-color: #c9a4ff; }
.box.rev { border-color: #7ee787; }
.box h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
  color: #8b909c; margin-bottom: 4px; font-weight: 600; }
.row { display: flex; padding: 6px 0; border-bottom: 1px solid #1d2330; font-size: 13px; }
.row .k { color: #8b909c; width: 84px; flex-shrink: 0; }
.row .v { color: #e3e6ec; word-break: break-word; }
.act { font-family: Consolas,monospace; color: #ffd866; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 5px; font-size: 12px; font-weight: 600; }
.p-on_path { background: #1f3a28; color: #7ee787; }
.p-off_path { background: #3a2525; color: #ff9f9f; }
.p-def { background: #2c3344; color: #aeb4c0; }
"""

_JS = r"""
const DATA = __PAYLOAD__;
const T = DATA.trajectories;
const DW = DATA.dev_w, DH = DATA.dev_h;
let ti = 0, si = 0;

function esc(s){ return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function pill(l){ const c=['on_path','off_path'].includes(l)?'p-'+l:'p-def';
  return l?`<span class="pill ${c}">${esc(l)}</span>`:''; }

function fillSelect(){
  const sel=document.getElementById('sel');
  sel.innerHTML=T.map((t,i)=>{
    const ok=t.success===true?'✓':(t.success===false?'✗':'·');
    return `<option value="${i}">${ok} ${esc(t.id)} — ${esc((t.instruction||'').slice(0,70))}</option>`;
  }).join('');
  sel.onchange=()=>{ ti=+sel.value; si=0; renderTask(); render(); };
}

function renderTask(){
  const t=T[ti];
  let tg='';
  if(t.targets && Object.keys(t.targets).length)
    tg=Object.entries(t.targets).map(([k,v])=>`<span class="tg">${esc(k)}=${esc(String(v))}</span>`).join('');
  const st=t.success===true?'<span class="ok">成功 ✓</span>':(t.success===false?'<span class="fail">失败 ✗</span>':esc(t.status||''));
  document.getElementById('task').innerHTML=
    `<span class="lbl">任务</span>${esc(t.instruction)} &nbsp; ${st}`
    + (tg?`<div style="margin-top:6px"><span class="lbl">目标</span>${tg}</div>`:'');
}

function render(){
  const t=T[ti], s=t.steps[si];
  document.getElementById('counter').textContent=`第 ${si+1} / ${t.steps.length} 步`;
  document.getElementById('prev').disabled=si===0;
  document.getElementById('next').disabled=si===t.steps.length-1;

  let mk='', bb='';
  if(s.x!=null) mk=`<div class="marker" style="left:${(s.x/DW*100).toFixed(2)}%;top:${(s.y/DH*100).toFixed(2)}%"></div>`;
  if(s.bbox && s.bbox.w) bb=`<div class="bbox" style="left:${(s.bbox.x/DW*100).toFixed(2)}%;top:${(s.bbox.y/DH*100).toFixed(2)}%;width:${(s.bbox.w/DW*100).toFixed(2)}%;height:${(s.bbox.h/DH*100).toFixed(2)}%"></div>`;
  const bImg=s.before_img?`<div class="wrap"><img src="${s.before_img}">${bb}${mk}</div>`:`<div class="wrap" style="width:300px;height:200px;display:flex;align-items:center;justify-content:center;color:#6b7180">无截图</div>`;
  const aImg=s.after_img?`<div class="wrap"><img src="${s.after_img}"></div>`:`<div class="wrap" style="width:300px;height:200px;display:flex;align-items:center;justify-content:center;color:#6b7180">无截图</div>`;
  document.getElementById('shots').innerHTML=
    `<div class="shotbox"><div class="cap">操作前(红点=点击,黄框=目标元素)</div>${bImg}</div>
     <div class="arrow">→</div>
     <div class="shotbox"><div class="cap">操作后</div>${aImg}</div>`;

  let coord=s.x!=null?` @(${s.x}, ${s.y})`:'';
  let h=`<div class="sn">步骤 ${s.i} ${pill(s.label)}</div>
    <div class="what">${esc(s.elem)||esc(s.type)||'(动作)'}</div>`;
  if(s.sub) h+=`<div class="box"><h4>这一步要做什么</h4>${esc(s.sub)}</div>`;
  if(s.thinking && s.thinking!==s.sub) h+=`<div class="box think"><h4>Agent 思考</h4>${esc(s.thinking)}</div>`;
  h+=`<div class="row"><span class="k">动作</span><span class="v act">${esc(s.type)}${coord}</span></div>`;
  if(s.text) h+=`<div class="row"><span class="k">输入</span><span class="v act">${esc(s.text)}</span></div>`;
  if(s.role) h+=`<div class="row"><span class="k">元素角色</span><span class="v">${esc(s.role)}</span></div>`;
  if(s.had_effect!=null) h+=`<div class="row"><span class="k">是否生效</span><span class="v">${s.had_effect?'<span class=ok>是</span>':'<span class=fail>否(无变化)</span>'}</span></div>`;
  if(s.reverse) h+=`<div class="box rev"><h4>反向推理判定</h4>${esc(s.reverse)}</div>`;
  if(s.evidence) h+=`<div class="row"><span class="k">标注依据</span><span class="v">${esc(s.evidence)}</span></div>`;
  document.getElementById('info').innerHTML=h;
}

function go(d){ const n=si+d, t=T[ti]; if(n>=0&&n<t.steps.length){ si=n; render(); } }
document.getElementById('prev').onclick=()=>go(-1);
document.getElementById('next').onclick=()=>go(1);
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft')go(-1);
  if(e.key==='ArrowRight'||e.key===' '){e.preventDefault();go(1);} });

if(T.length){ fillSelect(); renderTask(); render(); }
else document.getElementById('main').innerHTML='<div style="padding:40px;color:#8b909c">没有轨迹数据</div>';
"""


def render_html(p: Dict[str, Any]) -> str:
    js = _JS.replace("__PAYLOAD__", json.dumps(p, ensure_ascii=False))
    n = len(p["trajectories"])
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>采集轨迹查看器</title><style>{_CSS}</style></head>
<body>
<div id="bar">
  <h1>采集轨迹</h1>
  <select id="sel"></select>
  <span style="color:#8b909c;font-size:12px">共 {n} 条</span>
  <div class="spacer"></div>
  <button id="prev">‹ 上一步</button>
  <span id="counter">—</span>
  <button id="next">下一步 ›</button>
</div>
<div id="task"></div>
<div id="main">
  <div class="shots" id="shots"></div>
  <div id="info"></div>
</div>
<script>{js}</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="采集轨迹查看器(带截图)")
    ap.add_argument("path", help="exec_results.json 或含它的目录")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()
    root = Path(args.path)
    p = build(root)
    base = root if root.is_dir() else root.parent
    out = Path(args.out) if args.out else base / "trajectory_view.html"
    out.write_text(render_html(p), encoding="utf-8")
    nstep = sum(len(t["steps"]) for t in p["trajectories"])
    print(f"[OK] {len(p['trajectories'])} 条轨迹 / {nstep} 步 -> {out}")
    print(f"     浏览器打开: {out.resolve()}")


if __name__ == "__main__":
    main()
