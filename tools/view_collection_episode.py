"""采集轨迹交互式查看器(capability collection 格式)。

读取一个 episode 目录(含 trajectory.json + screenshots/),生成自包含单文件 HTML:
每步一屏 —— 操作前截图(红圈标出点击位置)、thinking、动作详情、step_type/had_effect
标注、操作后截图;键盘 ← → 翻页,顶部进度条。

用法:
  python tools/view_collection_episode.py <episode目录> [-o out.html]
"""
from __future__ import annotations
import argparse, base64, json, mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image
except Exception:
    Image = None


def _img_uri(p: Optional[Path], cap: int = 5_000_000) -> Optional[str]:
    if not p or not p.exists() or p.stat().st_size > cap:
        return None
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _img_size(p: Optional[Path]) -> Tuple[int, int]:
    if Image and p and p.exists():
        try:
            with Image.open(p) as im:
                return im.size
        except Exception:
            pass
    return (1280, 800)


def _click_xy(step: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    g = step.get("grounding") or {}
    c = g.get("element_center") or {}
    if isinstance(c, dict) and c.get("x") is not None:
        return int(c["x"]), int(c["y"])
    if g.get("x") is not None:
        return int(g["x"]), int(g["y"])
    try:
        prm = json.loads(step.get("action_json", "{}")).get("parameters", {})
        if prm.get("x") is not None:
            return int(prm["x"]), int(prm["y"])
    except Exception:
        pass
    return None


def _act(step: Dict[str, Any]) -> str:
    try:
        a = json.loads(step.get("action_json", "{}"))
        t = a.get("action_type") or a.get("action") or "?"
        prm = a.get("parameters", {})
        bits = [t]
        if "x" in prm:
            bits.append(f"({prm.get('x')},{prm.get('y')})")
        if prm.get("text"):
            bits.append(f'text="{prm.get("text")}"')
        if prm.get("keys"):
            bits.append(f"keys={prm.get('keys')}")
        return " ".join(str(b) for b in bits)
    except Exception:
        return step.get("action_json", "")[:80]


def build(ep_dir: Path, out: Path, traj_name: str = "trajectory.json") -> Path:
    tj = json.loads((ep_dir / traj_name).read_text(encoding="utf-8"))
    meta, steps = tj.get("meta", {}), tj.get("steps", [])
    ss = ep_dir / "screenshots"
    frames = [s.get("frame") or f"step{i:02d}.png" for i, s in enumerate(steps)]

    cards = []
    for i, s in enumerate(steps):
        before = ss / frames[i]
        after = ss / (frames[i + 1] if i + 1 < len(frames) else "final.png")
        bw, bh = _img_size(before)
        xy = _click_xy(s)
        dot = ""
        if xy:
            dot = (f'<div class="dot" style="left:{xy[0]/bw*100:.2f}%;'
                   f'top:{xy[1]/bh*100:.2f}%"></div>')
        a = s.get("annotation", {})
        sub = a.get("reverse_sub_instruction") or s.get("instruction") or ""
        think = (s.get("thinking") or "")[:600]
        eff = a.get("had_effect")
        eff_b = ("ok" if eff else "no") if eff is not None else "?"
        cards.append({
            "i": i, "before": _img_uri(before) or "", "after": _img_uri(after) or "",
            "dot": dot, "act": _act(s), "think": think, "sub": sub,
            "stype": a.get("step_type", ""), "eff": eff_b,
            "done": bool(a.get("step_completed")),
        })

    title = f"{meta.get('instruction_id','?')} — {meta.get('final_status','?')} — {len(steps)}步"
    data = json.dumps(cards, ensure_ascii=False)
    instr = (meta.get("instruction", "") or "").replace("<", "&lt;")
    html = """<!doctype html><html><head><meta charset="utf-8"><title>__T__</title>
<style>
body{margin:0;font:14px/1.5 system-ui,Segoe UI,sans-serif;background:#0f1115;color:#e6e6e6}
header{padding:10px 16px;background:#171a21;border-bottom:1px solid #2a2f3a}
h1{font-size:15px;margin:0 0 4px} .instr{color:#9aa4b2;font-size:13px}
.bar{display:flex;gap:2px;padding:6px 16px;background:#13161c;flex-wrap:wrap}
.bar span{width:18px;height:6px;border-radius:2px;background:#39414f;cursor:pointer}
.bar span.cur{background:#5b8cff} .bar span.no{background:#7a3b3b}
.wrap{display:flex;gap:14px;padding:14px 16px;align-items:flex-start;flex-wrap:wrap}
.col{flex:1;min-width:380px}
.imgbox{position:relative;border:1px solid #2a2f3a;border-radius:6px;overflow:hidden}
.imgbox img{width:100%;display:block}
.dot{position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border:3px solid #ff4d4d;
border-radius:50%;box-shadow:0 0 0 2px rgba(255,77,77,.4)}
.lbl{font-size:12px;color:#7e8796;margin:6px 0 2px}
.meta{background:#171a21;border:1px solid #2a2f3a;border-radius:6px;padding:10px 12px;margin-top:6px}
.k{color:#7e8796} .act{color:#ffd479;font-family:ui-monospace,monospace}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;margin-right:6px}
.t-prog{background:#2b4b2b} .t-no{background:#5a2b2b} .t-other{background:#39414f}
.eff-ok{color:#7ee07e} .eff-no{color:#ff7e7e}
.nav{padding:10px 16px;display:flex;gap:10px;align-items:center}
button{background:#2a3242;color:#e6e6e6;border:1px solid #3a4456;border-radius:6px;padding:6px 14px;cursor:pointer}
.think{white-space:pre-wrap;color:#c7cedb;font-size:13px}
</style></head><body>
<header><h1>__T__</h1><div class="instr">__I__</div></header>
<div class="bar" id="bar"></div>
<div class="nav"><button onclick="go(-1)">← 上一步</button>
<span id="pos"></span><button onclick="go(1)">下一步 →</button>
<span class="k">(键盘 ← → 翻页)</span></div>
<div class="wrap">
 <div class="col"><div class="lbl">操作前(红圈=点击位置)</div>
   <div class="imgbox"><img id="bimg"><span id="bdot"></span></div></div>
 <div class="col"><div class="lbl">操作后(动作结果)</div>
   <div class="imgbox"><img id="aimg"></div>
   <div class="meta">
     <div><span id="tags"></span></div>
     <div style="margin-top:6px"><span class="k">动作:</span> <span class="act" id="act"></span></div>
     <div style="margin-top:6px"><span class="k">子指令:</span> <span id="sub"></span></div>
     <div style="margin-top:6px"><span class="k">思考:</span><div class="think" id="think"></div></div>
   </div></div>
</div>
<script>
var D=__DATA__,cur=0;
function tag(t,c){return '<span class="tag '+c+'">'+t+'</span>';}
function render(){var s=D[cur];
 document.getElementById('bimg').src=s.before;
 document.getElementById('aimg').src=s.after;
 document.getElementById('bdot').outerHTML='<span id="bdot">'+s.dot+'</span>';
 document.getElementById('act').textContent=s.act;
 document.getElementById('sub').textContent=s.sub||'—';
 document.getElementById('think').textContent=s.think||'—';
 var st=s.stype||'', c=st=='progress'?'t-prog':(st.indexOf('off')>=0||st=='impossible_stop'?'t-no':'t-other');
 var tg=tag('step '+s.i,'t-other')+tag(st||'?',c)+
   '<span class="'+(s.eff=='ok'?'eff-ok':'eff-no')+'">had_effect='+s.eff+'</span>'+
   (s.done?'  <span class="eff-ok">✓done</span>':'');
 document.getElementById('tags').innerHTML=tg;
 document.getElementById('pos').textContent=(cur+1)+' / '+D.length;
 var b=document.getElementById('bar').children;
 for(var i=0;i<b.length;i++){b[i].className=(i==cur?'cur':(D[i].eff=='no'?'no':''));}
}
function go(d){cur=Math.max(0,Math.min(D.length-1,cur+d));render();}
window.onload=function(){var bar=document.getElementById('bar');
 D.forEach(function(s,i){var x=document.createElement('span');x.onclick=function(){cur=i;render();};bar.appendChild(x);});
 render();};
document.onkeydown=function(e){if(e.key=='ArrowLeft')go(-1);if(e.key=='ArrowRight')go(1);};
</script></body></html>"""
    html = (html.replace("__T__", title).replace("__I__", instr)
            .replace("__DATA__", data))
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ep_dir")
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--traj", default="trajectory.json",
                    help="trajectory json filename (e.g. trajectory_trimmed.json)")
    args = ap.parse_args()
    ep = Path(args.ep_dir)
    out = Path(args.out) if args.out else ep / "view.html"
    p = build(ep, out, args.traj)
    print("wrote", p)
